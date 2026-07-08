# r.in.landsat

A [GRASS GIS](https://grass.osgeo.org/) addon that downloads and
imports Landsat Collection 2 Level-2 imagery (surface reflectance +
surface temperature) directly into the current project using the
[cubo](https://github.com/ESDS-Leipzig/cubo) Python library, from
**Microsoft Planetary Computer** (no credentials required).

```
g.region n=0.52 s=0.48 e=33.34 w=33.28 res=0:00:00.970

r.in.landsat start=2025-01-01 end=2025-07-01 clouds=70 \
  output=l8 -c strds=l8
```

## Why

Sentinel-2 has no thermal band, so anything needing land surface
temperature (surface energy balance, evapotranspiration, crop water
stress) has to come from elsewhere. Landsat 8/9 Collection 2 Level 2
provides that as a ready-to-use, atmospherically-corrected Surface
Temperature product (`lwir11`, Kelvin) alongside surface reflectance
(`coastal, blue, green, red, nir08, swir16, swir22` - OLI bands 1-7),
following the same no-account, cubo/STAC-based pattern as
[r.in.sentinel](https://github.com/YannChemin/r.in.sentinel) and
[r.in.dem](https://github.com/YannChemin/r.in.dem).

## Physical units

Bands arrive already in physical units - reflectance as `[0-1]`,
`lwir11` as Kelvin - since Planetary Computer's STAC metadata carries
the USGS Collection 2 Level 2 scale/offset and `cubo`/`stackstac`
applies it automatically. This is the opposite of `r.in.sentinel`,
which deliberately leaves Sentinel-2 as raw DN (its STAC metadata has
no such transform). Applying a manual rescale on top of an
already-scaled Landsat band was tried and confirmed wrong empirically
(it turned real ~310 K surface temperatures into a meaningless uniform
~150 K) - so don't add one back.

## Cloud masking

The **c** flag nulls out pixels where `qa_pixel` bit 3 (cloud) or bit
4 (cloud shadow) is set, in every band for that date.

## Output naming

Raster maps are named `{output}_{YYYYMMDD}_{band}`, e.g.
`l8_20250222_lwir11`. One `i.group` per acquisition date. Pass
`strds=`*prefix* to also register one STRDS per band; only maps
confirmed to exist in the project after import are registered.

## See also

- [r.in.sentinel](https://github.com/YannChemin/r.in.sentinel) - the
  same download/import pattern for Sentinel-1/2
- [t.crop.season](https://github.com/YannChemin/t.crop.season) - a
  consumer of this module's `lwir11` output for surface-energy-balance
  based irrigation/yield estimation (`i.albedo`, `i.emissivity`,
  `i.eb.*`, `i.biomass`)

## License

Public domain (Unlicense) — see [LICENSE](LICENSE).
