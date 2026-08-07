# North Yorkshire school catchments

Working towards **average house price per school catchment area in North Yorkshire**.

This first pass renders the catchment boundaries around **Great Ouseburn Community
Primary School** (URN 121393, YO26 9RG). House prices are not joined in yet.

> **No figure is committed here.** The rendered map is derived from the NYC
> boundaries, so publishing it would publish the boundaries — and their onward
> licence is unconfirmed (see [`data/README.md`](data/README.md)). Run
> `make map-secondary` to generate it locally into `outputs/`.

## ⚠️ The primary catchment geometry is missing

The map above shows **secondary** catchments as a stand-in. It is not what we
ultimately want, and here is why we can't yet have what we want:

North Yorkshire Council supplied the primary layer as three files — `.dbf`
(293 school names, Great Ouseburn among them, catchment code 2327), `.shx`
(an index of 293 shapes), and `.prj.txt` — but **without the `.shp`**. The `.shp`
is the file that holds the boundary coordinates. The polygons cannot be
reconstructed from the name table and the index alone.

**Action: re-request the `.shp` from NYC.** Once it lands in `data/raw/`,
`make map` produces the primary map with no code changes.

## Quickstart

```bash
uv sync
make map              # primary — fails with a clear message until the .shp arrives
make map-secondary    # the stand-in shown above
```

Source data is not committed — see [`data/README.md`](data/README.md) for what to
put in `data/raw/` and where it came from.

## Two gotchas worth knowing about

**The projection sidecars are named `.prj.txt`, not `.prj`.** GDAL ignores them,
so both layers load with *no CRS at all* and would silently plot in the wrong
place if you let them. `ny_catchments.config` assigns the CRS explicitly:
secondary is British National Grid (EPSG:27700), primary is "MapInfo Generic
Lat/Long" (EPSG:4326). The two layers are **not** in the same CRS — everything is
reprojected to BNG so distances and the scale bar are in metres.

**The geometry is PolygonZ.** The Z is a MapInfo artefact and carries no meaning;
it's dropped on load.

## Layout

```
src/ny_catchments/
  config.py   paths, per-layer CRS specs, the focal school's coordinates
  io.py       sidecar validation + loading/reprojection
  plot.py     the map
scripts/make_map.py
```

## Where this is going

1. ~~Catchment boundaries~~ — done, pending the primary `.shp`.
2. Join HM Land Registry Price Paid transactions to catchments via ONSPD postcode
   centroids.
3. Aggregate to mean/median price per catchment, probably with a recency window
   and some control for property type and floor area.

Design of the map follows a single-hue approach on purpose: identity and location
are the job here, so context polygons stay recessive neutral and one hue marks the
focal catchment. That leaves the colour budget free for a sequential ramp when
prices arrive.

## Licence

Code is MIT. **The data is not** — see [`data/README.md`](data/README.md).
