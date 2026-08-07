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

## National reference data — read-only mirror

Price Paid, ONSPD and the EPC register are all large public downloads already
held by the sibling asylum-site study. This project reads them **in place and
read-only**; nothing here writes to that directory.

    /Users/matt/src/asylum-site-local-impacts/data/raw/
      land_registry/pp-complete.csv     ~5.1GB   HM Land Registry Price Paid (OGL)
      onspd/ONSPD_MAY_2026.zip          ~247MB   ONS Postcode Directory (OGL)
      epc/domestic-csv.zip              ~6.5GB   EPC domestic register

Override the location with `NY_CATCHMENTS_MIRROR` if it moves. If you are setting
this up fresh, all three are public downloads and none needs the sibling project.

Note the EPC archive begins in **2012**. A dwelling last certified before then —
or never certified, since a certificate is only required on sale or let — has no
floor area and drops out of the £/m² figures.

## Generated files

`data/interim/` (gitignored) holds:

| File | Contents |
|---|---|
| `transactions_<layer>.parquet` | Located sales, one row per transaction |
| `epc_floor_areas.parquet` | Cached EPC extract, so re-matching skips the archive scan |
| `transactions_<layer>_with_epc.parquet` | The above plus floor area and £/m² |

**These are address-level extracts and must not be published.** Only aggregates
may leave the repo — and even those are currently held back pending the licence
question above, so `outputs/` is gitignored too.

## School locations — DfE Get Information About Schools

`edubasealldata20260501.csv` from the sibling project provides Easting/Northing
per URN. Great Ouseburn Community Primary School is URN 121393, postcode YO26 9RG,
at E 444791 / N 461825.
