## DESCRIPTION

*r.in.landsat* downloads Landsat Collection 2 Level-2 imagery (surface
reflectance + surface temperature) directly into the current GRASS GIS
project using the [cubo](https://github.com/ESDS-Leipzig/cubo) Python
library, from **Microsoft Planetary Computer** (no credentials
required). Each acquisition date is imported as individual raster maps
and grouped with *i.group*, following the same pattern as
[r.in.sentinel](https://github.com/YannChemin/r.in.sentinel).

```
g.region n=0.52 s=0.48 e=33.34 w=33.28 res=30

r.in.landsat start=2025-01-01 end=2025-07-01 clouds=70 \
  output=l8 -c strds=l8
```

### Bands

Default bands are the Planetary Computer `landsat-c2-l2` asset names:
`coastal, blue, green, red, nir08, swir16, swir22` (surface
reflectance, OLI bands 1-7), `lwir11` (surface temperature, already
atmospherically corrected - no separate LST retrieval needed), and
`qa_pixel` (bitmask QA band).

### Physical units

Unlike *r.in.sentinel* (which leaves Sentinel-2 as raw DN), bands here
are rescaled to physical units on import, using the official USGS
Collection 2 Level 2 scale/offset factors:

- Surface reflectance bands: `reflectance = DN * 0.0000275 - 0.2` (range 0-1)
- `lwir11` (surface temperature): `temperature_K = DN * 0.00341802 + 149.0`

`qa_pixel` is left as an integer bitmask.

### Cloud masking

The **c** flag nulls out pixels where QA_PIXEL bit 3 (cloud) or bit 4
(cloud shadow) is set, in every band for that date (auto-adds
`qa_pixel` to the band list if not already requested).

### Output naming

Raster maps are named `{output}_{YYYYMMDD}_{band}`, e.g.
`l8_20250222_lwir11`. One *i.group* per acquisition date:
`{output}_{YYYYMMDD}`.

### Space-Time Raster Dataset (STRDS)

Pass **strds**=*prefix* to additionally register one STRDS per band
(`{prefix}_{band}`, e.g. `l8_red`, `l8_lwir11`). Only maps confirmed to
exist in the current project after import are registered - a band
that failed to import for a given date is silently excluded from its
STRDS rather than breaking `t.register` for the whole run.

## NOTES

Landsat 8/9 revisit is 16 days each (8 days combined, since both share
the `landsat-c2-l2` collection) - expect far sparser dates than
Sentinel-1/2 over the same period.

## SEE ALSO

*[r.in.sentinel](r.in.sentinel.md), [i.albedo](i.albedo.md),
[i.emissivity](i.emissivity.md), [i.eb.netrad](i.eb.netrad.md),
[i.eb.soilheatflux](i.eb.soilheatflux.md),
[i.eb.hsebal95](i.eb.hsebal95.md), [i.eb.evapfr](i.eb.evapfr.md),
[i.biomass](i.biomass.md)*

## AUTHOR

Yann Chemin
