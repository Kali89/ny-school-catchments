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
make all              # the full pipeline
```

Or stage by stage:

```bash
make map-secondary    # catchment boundaries around Great Ouseburn
make transactions     # locate Price Paid sales, assign each to a catchment
make floor-areas      # attach EPC floor areas (slow: scans the EPC archive)
make prices           # per-catchment table and choropleths
```

Source data is not committed — see [`data/README.md`](data/README.md) for what to
put in `data/raw/` and where it came from.

## What it measures

Three figures per catchment, deliberately reported together:

| Measure | Why it's there |
|---|---|
| **Mean** price | What most people mean by "average". |
| **Median** price | The headline. Price distributions are strongly right skewed — a handful of country houses drags the mean above anything a buyer would meet. |
| **Median price per m²** | The comparable figure. |

The third matters more than it looks. A raw average mostly tracks *what kind of
housing a catchment contains*, not how sought-after it is. Fulford (York) is 8th
on median price but 2nd on £/m², because its median home is 91m² against
Boroughbridge's 117m². Ranking catchments on raw price largely ranks them on
floor area.

Transaction counts sit beside every figure, and catchments with fewer than 30
sales are not reported at all — a median over a handful of rural sales says more
about which houses happened to change hands than about the area.

## Data traps handled explicitly

Each of these fails *silently* — producing plausible output that is wrong — so
each is handled in code rather than left to a default. Three were inherited from
the sibling asylum-site study, which hit them first.

**ONSPD holds two coordinate systems in the same unlabelled columns.** Northern
Ireland eastings/northings are Irish Grid, not British National Grid. Read as BNG
they land ~250km away *together*, forming a plausible cluster rather than visible
outliers. Filtered by country code.

**The null-island sentinel.** Postcodes with no grid reference carry
`lat = 99.999999`, `long = 0.0`, `gridind = 9`. Dropped on load.

**Price Paid category B is excluded.** Category B covers repossessions, portfolio
transfers and other sales that are not open-market prices. Including them biases
a "what does a house cost here" figure downward.

**Terminated postcodes are retained.** A house sold in 2021 may sit in a postcode
since retired; filtering to "live today" would silently drop those sales.

**The EPC join has to reach the same dwelling from two registers that describe
it differently.** Price Paid splits the building ("130") from the dwelling
within it ("FLAT 2") across two fields; an EPC assessor types one line, and for
a flat that line usually names the *flat* — "Flat 2" with no building number at
all. No single key spans that, so matching runs as a **cascade of five keys,
most specific first**, each tried on what the previous ones left:

| Tier | Key | Share of matches |
|---|---|---:|
| building+flat | postcode + building + flat | 0.0% |
| building | postcode + building | 79.1% |
| flat+name | postcode + flat + name | 1.5% |
| flat | postcode + flat | 3.5% |
| name | postcode + first distinctive word | 15.9% |

Only rows whose key is *fully populated* are eligible for a tier — a property
with no building number cannot enter the building tier. That is what stops an
absent identifier behaving like a value and matching every other address that
also lacks one.

Getting here took three attempts, and none of the failures raised an error:

1. **Nulls silently dropped every house.** polars joins with `join_nulls=False`,
   so nulls never match — not even null-to-null. Most houses have no flat
   number, so the key dropped houses while still matching flats. The symptom was
   inverted and diagnostic: flats 45%, semis 9%.
2. **An empty-string sentinel then over-matched.** `(postcode, "", "")` is not an
   identifier — 3,946 postcodes had multiple certified addresses sharing it, up
   to 49 — so unnumbered named properties took an arbitrary neighbour's floor
   area, at a comfortable-looking 95%.
3. **Refusing every ambiguous match biased against flats.** Requiring an
   unambiguous key was safe but not neutral: it dropped flats at 55% while
   keeping 95% of houses, because several flats in one block genuinely share a
   name. That is a systematic bias, not a random one.

The cascade resolves all three. **96% of sales carry a floor area — detached
95.7%, semi 97.2%, terraced 96.1%, flats 93.8%** — all four within 3.5 points,
where before the spread was 50.

The remaining risk is honest rather than hidden: 15.9% of matches rest on the
loosest key, which cannot always tell "Rose Cottage" from "Rosebank" in the same
postcode. That share is reported in every output rather than assumed away, and
`composition_check()` compares matched against unmatched sales each run, so a
divergence between the population £/m² is computed on and the one behind the mean
and median stays visible.

Correcting the flat bias moved catchment £/m² by under 1% — flats are 11% of
sales county-wide. It mattered most for **Graham School (Scarborough), 39.8%
flats**, where the previous version was discarding over half of them.

## Two shapefile gotchas

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

## Distribution and change over time

`make periods` produces four outputs from a 20-year extract:

| Output | What it answers |
|---|---|
| `price_per_m2_distribution_*.png` | Ranked box plot — how bunched are catchments, and where does mine sit |
| `price_per_m2_rank_shift_*.png` | Slope chart of rank across three periods |
| `price_per_m2_excess_*.png` | Diverging bars — who moved outsized |
| `period_comparison_*.md` | The numbers behind all three |

**The main finding is how alike catchments are.** Across 38 reportable
catchments the middle half sit between £2,713 and £3,277/m² — a 20% spread
around the typical £2,885. But the *typical catchment's own* interquartile range
is 32% of its median. **The variation between houses inside a catchment is
larger than the variation between catchments.** Picking a catchment moves the
expected price per m² far less than picking a house within one does.

The extremes are real but few: Fulford (York) at £3,795 and Graham School
(Scarborough) at £1,746, a 2.2× range end to end.

Three things this analysis is careful about:

**Nominal, so comparisons are relative.** £/m² rose ~42% county-wide over twenty
years. An absolute rise means nothing on its own, so period comparisons report
each catchment's change *net of the county-wide change*. That is what "outsized"
has to mean.

**EPC coverage collapses in the early period** — 68.5% for 2006–2015 against
96.0% for 2021–2025, because the register starts in 2012. A pre-2012 sale has a
floor area only if the property was certified later, which happens when it is
marketed again. Early coverage is therefore a function of subsequent market
activity, not a random sample. Reported per period in every output.

**Thin catchments dominate the extremes.** The largest mover, Malton & Huntington
at +18.4pp, rests on 98 recent priced sales. Sale counts sit on the distribution
figure so a ranking can be read against the data behind it.

Periods cover whole calendar years; part-year 2026 is excluded so one window
isn't half-weighted against the others.

## Inequality, and where rich and poor sit side by side

`make inequality` produces three figures and a table. Two distinct questions are
kept apart, because conflating them would answer neither:

**How unequal is a catchment?** P90/P10 on price per m² — the top tenth of homes
cost this many times more per square metre than the bottom tenth. Gini is
reported alongside, but P90/P10 leads because it survives these sample sizes
better and states itself in a sentence.

**Is that inequality geographic?** A catchment can be unequal because expensive
and cheap homes are mixed street by street, or because it holds one wealthy
village and one deprived estate. Only the second is "rich and poor next to each
other". A variance decomposition on log £/m² splits the spread into between- and
within-neighbourhood parts, using LSOAs (~650 households) as the neighbourhood.

### What it shows

**Most inequality is not geographic.** The median catchment has only **10.7%** of
its price variation between neighbourhoods; even the most divided —
Tadcaster Grammar — reaches just 35%. Rich and poor homes are mixed at fine grain
almost everywhere in the county.

**Inequality barely tracks price.** Spearman between median £/m² and P90/P10 is
**−0.166**. The most unequal catchments are Filey (2.45×) and Graham,
Scarborough (2.42×) — one mid-priced, one the cheapest in the county.

**Sharp divides are real but local.** The steepest adjacent contrasts:

| Catchment | Richer | Poorer | Gap | Apart |
|---|---:|---:|---:|---:|
| Graham School | £2,182 | £1,284 | 1.70× | 372 m |
| Selby High & Brayton Academy Town area | £2,870 | £1,692 | 1.70× | 295 m |
| Skipton Girls' High & Ermysted's | £3,802 | £2,295 | 1.66× | 455 m |
| Rossett & Harrogate Grammar Town area | £4,510 | £2,732 | 1.65× | 219 m |

**Price and deprivation are not the same axis.** Spearman between a
neighbourhood's £/m² and its IMD 2020 rank is **+0.53** — related, but well
short of interchangeable. The report flags divides where they disagree: at Graham School
the *pricier* side of the sharpest divide is the *more* deprived one.

### Adjacency without boundaries

Two neighbourhoods count as adjacent when they contain postcodes within 500m of
each other, not when their polygons touch. This is deliberate, and it is not a
workaround for lacking LSOA boundaries: two rural LSOAs can share a long
boundary across open moorland while the places people actually live are
kilometres apart. Polygon contiguity would call that "next to each other". Sales
locations measure where people are close.

LSOAs are assigned to the catchment holding most of their sales. Only 58 of 419
span more than one, and just 32 fall below 80% purity.

## Where this is going

1. ~~Catchment boundaries~~ — done, pending the primary `.shp`.
2. ~~Join Price Paid to catchments via ONSPD postcode centroids~~ — done.
3. ~~Mean/median price and price per m² per catchment~~ — done.
4. **An inequality index per catchment** — not started. See below.

### On the inequality index

Not yet implemented, and worth a decision rather than a default. The measures
differ in what they'd actually say about a catchment:

- **Gini / IQR-to-median ratio** on sale prices — spread of what changes hands.
  Cheapest to compute, but in a thin rural market it mostly measures the mix of
  stock that happened to sell in the window.
- **P90/P10 ratio** — more robust than Gini at these sample sizes, and easier to
  explain ("the top decile costs N× the bottom").
- **£/m² dispersion rather than price dispersion** — separates "this area has a
  mix of big and small homes" from "this area has genuinely cheap and expensive
  land". Probably the more meaningful of the two, and only possible because the
  EPC join is already built.
- **A deprivation-based index** — ONSPD already carries the IMD 2020 decile per
  postcode, so a population-weighted spread of deprivation within a catchment is
  available essentially for free, and measures something quite different from
  price: who lives there, not what property costs.

These answer different questions and the right choice depends on what the index
is *for*. Worth settling before building.

Note that sample size bites harder here than for a median — a Gini over 30 sales
is very noisy — so the suppression threshold likely needs to be higher for this
measure than the 30 used elsewhere.

## Figure design

Boundary maps and choropleths use different colour strategies on purpose. The
boundary map's job is identity and location, so context polygons stay recessive
neutral and a single hue marks the focal catchment. The choropleths encode
magnitude, so they use one sequential hue light→dark with quantile class breaks —
equal-width bins would put almost every catchment in the bottom class, given the
skew. Catchments below the reporting threshold are hatched, never coloured, so
"no data" can't be misread as "cheap".

## Licence

Code is MIT. **The data is not** — see [`data/README.md`](data/README.md).
