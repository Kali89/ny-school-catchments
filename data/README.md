# Data

**Nothing in `data/raw/` is committed.** See the note in `.gitignore`.

## Catchment boundaries — North Yorkshire Council

Supplied directly by NYC, apparently as an FOI/EIR release (the bundle included
the Council's standard "Information Governance Appeals Notice"). **The onward
publication licence has not been confirmed**, which is why these files are not
committed to this public repository. Check with NYC's Information Governance team
(infogov@northyorks.gov.uk) before publishing the boundaries themselves.

Expected in `data/raw/`:

| Layer | Files | Status |
|---|---|---|
| Primary named catchments (`250901 nh Primary named catchments region`) | `.shp` `.shx` `.dbf` | **`.shp` MISSING** |
| Secondary Synergy areas (`250207 Synergy areas Secondary update July 2025 region`) | `.shp` `.shx` `.dbf` | complete |

### The missing primary geometry

The primary layer arrived without its `.shp`. The `.dbf` holds 293 school names
(including Great Ouseburn Community Primary School, catchment code 2327) and the
`.shx` indexes 293 shapes — but the `.shp`, which holds the boundary coordinates
themselves, was not included. The polygons cannot be reconstructed from the other
two files. **Re-request the `.shp` from NYC.**

### Projection sidecars

Both layers ship their projection as `.prj.txt` rather than `.prj`, so GDAL does
not read it and the layers load with no CRS. `ny_catchments.config` assigns the
CRS explicitly from the sidecars' documented contents:

- Secondary: `British_National_Grid` → EPSG:27700
- Primary: `MapInfo Generic Lat/Long` on a WGS84 spheroid → EPSG:4326

## House prices — HM Land Registry Price Paid

Not yet wired in. The full Price Paid dataset (`pp-complete.csv`, ~5.1GB) is
already downloaded at:

    ../asylum-site-local-impacts/data/raw/land_registry/pp-complete.csv

Price Paid is published under the Open Government Licence and contains a
postcode per transaction, so joining to catchments will go via ONSPD postcode
centroids (also present in that project).

## School locations — DfE Get Information About Schools

`edubasealldata20260501.csv` from the sibling project provides Easting/Northing
per URN. Great Ouseburn Community Primary School is URN 121393, postcode YO26 9RG,
at E 444791 / N 461825.
