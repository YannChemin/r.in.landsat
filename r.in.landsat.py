#!/usr/bin/env python3
# %Module
# % description: Downloads and imports Landsat Collection 2 Level-2 (surface reflectance + surface temperature) imagery using the cubo library via Microsoft Planetary Computer.
# % keyword: Import
# % keyword: imagery
# % keyword: satellite
# % keyword: Landsat
# % keyword: temperature
# % keyword: download
# % keyword: STAC
# % keyword: Planetary Computer
# % keyword: cloud
# %end

# %option
# % key: collection
# % type: string
# % required: no
# % multiple: no
# % answer: landsat-c2-l2
# % description: STAC collection ID (Planetary Computer)
# % guisection: Config
# %end

# %option
# % key: bands
# % type: string
# % required: no
# % multiple: yes
# % answer: coastal,blue,green,red,nir08,swir16,swir22,lwir11,qa_pixel
# % description: Bands to download (Planetary Computer asset names). coastal/blue/green/red/nir08/swir16/swir22 map to OLI bands 1-7; lwir11 is the atmospherically-corrected Surface Temperature band (K); qa_pixel is the bitmask cloud/shadow/snow/water QA band.
# % guisection: Config
# %end

# %option
# % key: start
# % type: string
# % required: yes
# % multiple: no
# % description: Start date (YYYY-MM-DD)
# % guisection: Filter
# %end

# %option
# % key: end
# % type: string
# % required: yes
# % multiple: no
# % description: End date (YYYY-MM-DD)
# % guisection: Filter
# %end

# %option
# % key: resolution
# % type: integer
# % required: no
# % multiple: no
# % answer: 30
# % description: Spatial resolution in meters
# % guisection: Config
# %end

# %option
# % key: clouds
# % type: integer
# % required: no
# % multiple: no
# % description: Maximum cloud cover percentage [0, 100]
# % guisection: Filter
# %end

# %option
# % key: platform
# % type: string
# % required: no
# % multiple: no
# % options: any,landsat-8,landsat-9,landsat-7,landsat-5,landsat-4
# % answer: any
# % description: Restrict to a specific Landsat platform, or any (Landsat 8+9 Collection 2 share the same band/asset naming used here)
# % guisection: Filter
# %end

# %option
# % key: output
# % type: string
# % required: no
# % multiple: no
# % answer: landsat
# % description: Prefix for output raster map names
# % guisection: Output
# %end

# %option
# % key: stac
# % type: string
# % required: no
# % multiple: no
# % answer: https://planetarycomputer.microsoft.com/api/stac/v1
# % description: STAC endpoint URL
# % guisection: Config
# %end

# %option
# % key: strds
# % type: string
# % required: no
# % multiple: no
# % description: Prefix for Space-Time Raster Dataset names (one STRDS per band, e.g. strds=l8 → l8_red, l8_lwir11 …)
# % guisection: Output
# %end

# %flag
# % key: c
# % description: Null out cloud/cloud-shadow pixels using the qa_pixel QA band (auto-added if not listed)
# %end

# %flag
# % key: l
# % description: List available dates/scenes and exit without downloading
# %end

# %flag
# % key: p
# % description: Print region info and exit
# %end

# %flag
# % key: r
# % description: Create true-color RGB composite with r.composite after import (auto-adds red, green, blue if not listed)
# %end

# %rules
# % exclusive: -l, -p
# %end

import sys
import tempfile

import grass.script as gs

# True-color composite: Landsat Collection 2 asset names for red, green, blue
RGB_BANDS = ("red", "green", "blue")

# Optical (surface reflectance) bands: USGS Collection 2 Level 2 scale/offset
# to convert the raw scaled integer DN to reflectance [0-1].
# reflectance = DN * SR_SCALE + SR_OFFSET
SR_BANDS = {"coastal", "blue", "green", "red", "nir08", "swir16", "swir22"}
SR_SCALE = 0.0000275
SR_OFFSET = -0.2

# Thermal (surface temperature) band: USGS Collection 2 Level 2 scale/offset
# to convert the raw scaled integer DN to Kelvin.
# temperature_K = DN * ST_SCALE + ST_OFFSET
ST_BANDS = {"lwir11"}
ST_SCALE = 0.00341802
ST_OFFSET = 149.0

# qa_pixel is a bitmask, not a physical quantity - never rescaled.
QA_BANDS = {"qa_pixel", "qa_radsat", "qa_aerosol"}

# QA_PIXEL bit positions (USGS Landsat Collection 2 Level 2 Science Product
# Guide): bit 1 = dilated cloud, bit 2 = cirrus, bit 3 = cloud,
# bit 4 = cloud shadow, bit 5 = snow, bit 6 = clear, bit 7 = water.
QA_BIT_CLOUD = 3
QA_BIT_CLOUD_SHADOW = 4

# Semantic label prefix per band (kept short; GRASS semantic labels have no
# enforced vocabulary for Landsat, so these are simple, self-describing tags).
SEMANTIC_LABELS = {
    "coastal": "L_coastal",
    "blue": "L_blue",
    "green": "L_green",
    "red": "L_red",
    "nir08": "L_nir",
    "swir16": "L_swir1",
    "swir22": "L_swir2",
    "lwir11": "L_ST",
    "qa_pixel": "L_QA",
}


def get_region_center_latlon():
    """Compute the center lat/lon and approximate edge size (in meters) of the
    current GRASS computational region.

    Returns
    -------
    tuple
        (lat_center, lon_center, edge_size_m)
    """
    proj_info = gs.parse_command("g.proj", flags="p", format="shell")
    is_latlong = proj_info.get("proj") in ("ll", "longlat")

    if is_latlong:
        region = gs.parse_command("g.region", flags="p", format="shell")
        n = float(region["n"])
        s = float(region["s"])
        e = float(region["e"])
        w = float(region["w"])
        lat_center = (n + s) / 2.0
        lon_center = (e + w) / 2.0
        deg_ns = abs(n - s)
        deg_ew = abs(e - w)
        edge_size_m = max(deg_ns, deg_ew) * 111320.0
    else:
        region = gs.parse_command("g.region", flags="pb", format="shell")
        lat_center = float(region["ll_clat"])
        lon_center = float(region["ll_clon"])
        rows = int(region["rows"])
        cols = int(region["cols"])
        nsres = float(region["nsres"])
        ewres = float(region["ewres"])
        edge_size_m = max(rows * nsres, cols * ewres)

    return lat_center, lon_center, edge_size_m


def download_cube(lat, lon, collection, start, end, bands, edge_size_m, resolution,
                   stac_url, clouds=None, platform=None):
    """Download a data cube using the cubo library (see r.in.sentinel for the
    same pattern applied to Sentinel-1/2)."""
    try:
        import cubo
    except ImportError:
        gs.fatal(
            "The 'cubo' Python library is not installed. "
            "Install it with: pip install cubo"
        )

    edge_size = int(round(edge_size_m / resolution))
    if edge_size < 2:
        edge_size = 2
    if edge_size % 2 != 0:
        edge_size += 1

    gs.verbose(
        f"Requesting cube: center=({lat:.4f}, {lon:.4f}), "
        f"edge_size={edge_size}px, resolution={resolution}m"
    )

    query = {}
    if clouds is not None:
        query["eo:cloud_cover"] = {"lt": clouds}
    if platform and platform != "any":
        query["platform"] = {"eq": platform}
    kwargs = {"query": query} if query else {}

    da = cubo.create(
        lat=lat, lon=lon, collection=collection, start_date=start, end_date=end,
        bands=bands, edge_size=edge_size, units="px", resolution=float(resolution),
        stac=stac_url, gee=False, **kwargs,
    )

    gs.verbose("Computing data cube (downloading data)…")
    da = da.compute()
    return da


def import_band_to_grass(band_array_2d, map_name, crs_str, transform):
    """Write a 2-D band array to a temp GeoTIFF and import it into GRASS GIS."""
    import numpy as np
    import rasterio
    from rasterio.crs import CRS

    tmp_path = gs.tempfile(create=False) + ".tif"

    try:
        arr = band_array_2d.values if hasattr(band_array_2d, "values") else band_array_2d
        arr = np.asarray(arr, dtype=np.float64)

        finite_mask = np.isfinite(arr)
        nodata_val = float("nan")
        dtype_str = "float32"
        arr = np.where(finite_mask, arr, np.nan).astype(np.float32)

        epsg_int = int(float(crs_str.replace("EPSG:", "")))
        crs_obj = CRS.from_epsg(epsg_int)

        height, width = arr.shape
        with rasterio.open(
            tmp_path, "w", driver="GTiff", height=height, width=width, count=1,
            dtype=dtype_str, crs=crs_obj, transform=transform, nodata=nodata_val,
        ) as dst:
            dst.write(arr, 1)

        gs.run_command(
            "r.import", input=tmp_path, output=map_name, extent="region",
            overwrite=True, quiet=True,
        )
    finally:
        import os

        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def apply_qa_cloud_mask(band_maps_by_name, output_prefix, date_str):
    """Null out cloud/cloud-shadow pixels (QA_PIXEL bits 3/4) in every
    imported band for this date. Returns the cloud-mask raster name."""
    qa_map = band_maps_by_name.get("qa_pixel")
    if not qa_map:
        gs.warning(f"{date_str}: qa_pixel not imported; skipping cloud masking.")
        return None

    cloud_mask = f"{output_prefix}_{date_str}_cloudmask"
    gs.mapcalc(
        f"{cloud_mask} = if((int({qa_map}) >> {QA_BIT_CLOUD}) & 1 || "
        f"(int({qa_map}) >> {QA_BIT_CLOUD_SHADOW}) & 1, 1, null())",
        overwrite=True, quiet=True,
    )

    nulled = 0
    for band_name, map_name in band_maps_by_name.items():
        if band_name == "qa_pixel":
            continue
        gs.mapcalc(
            f"{map_name} = if(isnull({cloud_mask}), {map_name}, null())",
            overwrite=True, quiet=True,
        )
        nulled += 1
    gs.verbose(f"{date_str}: cloud/shadow-masked {nulled} band(s).")
    return cloud_mask


def main():
    try:
        import numpy as np
        import pandas as pd
        from rasterio.transform import Affine
    except ImportError as e:
        gs.fatal(
            f"Required Python library not found: {e}. "
            "Install numpy, pandas, and rasterio."
        )

    collection = options["collection"]
    bands_raw = options["bands"]
    start = options["start"]
    end = options["end"]
    resolution = int(options["resolution"])
    clouds_raw = options["clouds"]
    platform = options["platform"]
    output_prefix = options["output"]
    stac_url = options["stac"]
    strds_prefix = options["strds"] if options["strds"] else None

    do_qa_mask = flags["c"]
    do_rgb = flags["r"]
    list_only = flags["l"]
    print_region = flags["p"]

    clouds = int(clouds_raw) if clouds_raw else None
    bands = [b.strip() for b in bands_raw.split(",") if b.strip()]

    if do_qa_mask and "qa_pixel" not in bands:
        gs.message("Adding qa_pixel band for cloud masking.")
        bands.append("qa_pixel")

    if do_rgb:
        added_rgb = [b for b in RGB_BANDS if b not in bands]
        if added_rgb:
            gs.message(f"Adding bands required for RGB composite: {', '.join(added_rgb)}")
            bands.extend(added_rgb)

    gs.message("Determining region centre and extent…")
    try:
        lat, lon, edge_size_m = get_region_center_latlon()
    except Exception as e:
        gs.fatal(f"Failed to determine region parameters: {e}")

    gs.message(
        f"Region centre: lat={lat:.4f}, lon={lon:.4f}, "
        f"approximate edge={edge_size_m:.0f} m"
    )

    if print_region:
        gs.message(f"lat={lat}, lon={lon}, edge_size_m={edge_size_m}, resolution={resolution}")
        return 0

    gs.message(f"Downloading {collection} data from {stac_url} …")
    gs.message(f"  Bands  : {', '.join(bands)}")
    gs.message(f"  Period : {start} → {end}")
    if clouds is not None:
        gs.message(f"  Max cloud cover: {clouds}%")
    if platform and platform != "any":
        gs.message(f"  Platform: {platform}")

    try:
        da = download_cube(
            lat=lat, lon=lon, collection=collection, start=start, end=end,
            bands=bands, edge_size_m=edge_size_m, resolution=resolution,
            stac_url=stac_url, clouds=clouds, platform=platform,
        )
    except Exception as e:
        gs.fatal(f"Failed to download data cube: {e}")

    if da.coords["time"].size == 0:
        gs.message("No scenes found for the given parameters. Exiting.")
        return 0

    n_scenes = da.coords["time"].size
    gs.message(f"Downloaded {n_scenes} scene(s).")

    if list_only:
        unique_dates_list = list(
            dict.fromkeys(
                pd.DatetimeIndex(da.coords["time"].values).strftime("%Y-%m-%d")
            )
        )
        gs.message("Available dates:")
        for d in unique_dates_list:
            print(d)
        return 0

    epsg = da.attrs.get("epsg", 4326)
    crs_str = f"EPSG:{epsg}"

    proj_info = gs.parse_command("g.proj", flags="p", format="shell")
    if proj_info.get("proj") in ("ll", "longlat"):
        res_deg = resolution / 111320.0
        gs.run_command("g.region", nsres=res_deg, ewres=res_deg)

    x = da.coords["x"].values
    y = da.coords["y"].values
    x_res = float(x[1] - x[0])
    y_res = float(y[1] - y[0])
    transform = Affine(x_res, 0, float(x[0]) - x_res / 2.0, 0, y_res, float(y[0]) - y_res / 2.0)

    times_pd = pd.DatetimeIndex(da.coords["time"].values)
    date_strs = times_pd.strftime("%Y%m%d")
    unique_dates = list(dict.fromkeys(date_strs))
    gs.message(f"Unique acquisition dates: {', '.join(unique_dates)}")

    imported_maps_total = 0
    groups_created = []
    band_map_registry = {str(b): [] for b in da.coords["band"].values}

    for date_str in unique_dates:
        indices = [i for i, d in enumerate(date_strs) if d == date_str]
        acq_time = times_pd[indices[0]]
        # Whole seconds only - see r.in.sentinel for why fractional seconds
        # corrupt GRASS's r.timestamp/t.register datetime round-trip.
        timestamp_str = acq_time.strftime("%d %b %Y %H:%M:%S")

        if len(indices) == 1:
            da_day = da.isel(time=indices[0])
        else:
            gs.verbose(f"  {date_str}: mosaicking {len(indices)} overlapping tile(s)…")
            da_day = da.isel(time=indices[0])
            for i in indices[1:]:
                da_day = da_day.combine_first(da.isel(time=i))

        band_maps = []
        band_maps_by_name = {}

        for j, b in enumerate(da.coords["band"].values):
            band_name = str(b)
            map_name = f"{output_prefix}_{date_str}_{band_name}"
            arr_2d = da_day.isel(band=j)

            try:
                import_band_to_grass(arr_2d, map_name, crs_str, transform)

                if band_name in SR_BANDS:
                    gs.mapcalc(
                        f"{map_name} = float({map_name}) * {SR_SCALE} + ({SR_OFFSET})",
                        overwrite=True, quiet=True,
                    )
                    gs.run_command("r.colors", map=map_name, color="grey", quiet=True)
                elif band_name in ST_BANDS:
                    gs.mapcalc(
                        f"{map_name} = float({map_name}) * {ST_SCALE} + ({ST_OFFSET})",
                        overwrite=True, quiet=True,
                    )
                    gs.run_command("r.colors", map=map_name, color="celsius", quiet=True)
                elif band_name in QA_BANDS:
                    gs.mapcalc(f"{map_name} = int({map_name})", overwrite=True, quiet=True)

                band_maps.append(map_name)
                band_maps_by_name[band_name] = map_name
                band_map_registry[band_name].append(map_name)
                imported_maps_total += 1

                gs.run_command("r.timestamp", map=map_name, date=timestamp_str, quiet=True)

                support_args = {
                    "map": map_name,
                    "source1": stac_url,
                    "source2": collection,
                    "history": f"band={band_name} date={date_str} epsg={epsg} resolution={resolution}m n_tiles={len(indices)}",
                }
                if band_name in SR_BANDS:
                    support_args["units"] = "reflectance (0-1)"
                elif band_name in ST_BANDS:
                    support_args["units"] = "K"
                sem_label = SEMANTIC_LABELS.get(band_name)
                if sem_label:
                    support_args["semantic_label"] = sem_label
                gs.run_command("r.support", quiet=True, **support_args)
            except Exception as e:
                gs.warning(f"Failed to import {map_name}: {e}")

        if do_qa_mask and band_maps_by_name:
            cloud_mask = apply_qa_cloud_mask(band_maps_by_name, output_prefix, date_str)
            if cloud_mask:
                band_maps.append(cloud_mask)
                band_map_registry.setdefault("cloudmask", []).append(cloud_mask)
                imported_maps_total += 1
                gs.run_command("r.timestamp", map=cloud_mask, date=timestamp_str, quiet=True)

        if band_maps:
            group_name = f"{output_prefix}_{date_str}"
            try:
                gs.run_command(
                    "i.group", group=group_name, subgroup=group_name,
                    input=",".join(band_maps), quiet=True,
                )
                groups_created.append(group_name)
                gs.message(f"Created group '{group_name}' with {len(band_maps)} band(s).")
            except Exception as e:
                gs.warning(f"Failed to create group '{group_name}': {e}")

        if do_rgb and band_maps:
            r_map, g_map, b_map = (
                f"{output_prefix}_{date_str}_red",
                f"{output_prefix}_{date_str}_green",
                f"{output_prefix}_{date_str}_blue",
            )
            if all(m in band_maps for m in (r_map, g_map, b_map)):
                rgb_name = f"{output_prefix}_{date_str}_RGB"
                try:
                    gs.run_command(
                        "r.composite", red=r_map, green=g_map, blue=b_map,
                        output=rgb_name, overwrite=True, quiet=True,
                    )
                    gs.message(f"  {date_str}: RGB composite → {rgb_name}")
                    band_map_registry.setdefault("RGB", []).append(rgb_name)
                    imported_maps_total += 1
                    gs.run_command("r.timestamp", map=rgb_name, date=timestamp_str, quiet=True)
                except Exception as e:
                    gs.warning(f"{date_str}: RGB composite failed: {e}")

    gs.message(
        f"Done. Imported {imported_maps_total} raster map(s) across {len(groups_created)} scene group(s)."
    )

    if strds_prefix and imported_maps_total > 0:
        # Confirm every candidate map actually exists in the current
        # mapset/project before registering it in a STRDS - a name being in
        # band_map_registry only means import_band_to_grass() didn't raise,
        # not that r.import necessarily left a valid map behind (e.g. an
        # edge tile with no overlap can still exit 0 while writing nothing
        # useful). One g.list call, not one g.findfile per map.
        mapset = gs.gisenv()["MAPSET"]
        existing_rasters = set(gs.list_grouped("raster").get(mapset, []))
        for band_name, map_list in band_map_registry.items():
            confirmed = [m for m in map_list if m in existing_rasters]
            missing = set(map_list) - existing_rasters
            for m in missing:
                gs.warning(f"'{m}' was not found in the current project after import; excluding it from STRDS registration.")
            band_map_registry[band_name] = confirmed

        gs.message("Creating Space-Time Raster Datasets…")
        try:
            import grass.temporal as tgis

            tgis.init()
        except Exception as e:
            gs.warning(f"Failed to initialise temporal framework: {e}")
        strds_created = []
        for band_name, map_list in band_map_registry.items():
            if not map_list:
                continue
            strds_name = f"{strds_prefix}_{band_name}"
            try:
                gs.run_command(
                    "t.create", type="strds", temporaltype="absolute", output=strds_name,
                    title=f"Landsat {collection} — band {band_name}",
                    description=f"Imported by r.in.landsat from {collection}, {start} to {end}, band {band_name}",
                    overwrite=True, quiet=True,
                )
                gs.run_command(
                    "t.register", type="raster", input=strds_name,
                    maps=",".join(map_list), overwrite=True, quiet=True,
                )
                strds_created.append(strds_name)
                gs.message(f"  STRDS '{strds_name}': {len(map_list)} map(s) registered.")
            except Exception as e:
                gs.warning(f"Failed to create/register STRDS '{strds_name}': {e}")

        if strds_created:
            gs.message(f"Created {len(strds_created)} STRDS: {', '.join(strds_created)}")

    return 0


if __name__ == "__main__":
    options, flags = gs.parser()

    try:
        import cubo  # noqa: F401
    except ImportError:
        gs.fatal("The 'cubo' Python library is required but not installed. Install it with: pip install cubo")

    sys.exit(main())
