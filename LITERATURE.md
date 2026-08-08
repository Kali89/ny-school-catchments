# Schools and house prices: what is already known

*Literature review, August 2026. Compiled to answer: does school quality raise
house prices, do house prices raise school results, or neither?*

## Short answer

**Yes, somebody has done this — many times, over about 25 years.** It is one of
the better-identified questions in urban economics, and the answer to all three
of your framings is "yes, partly".

1. **School quality does raise house prices.** Credible causal estimates cluster
   around **2–4% per standard deviation** of school quality. This is well
   established for England.
2. **House prices do raise measured school results**, mostly through *who ends up
   in the school* rather than through teaching. Residence-based admission sorts
   families by income, and raw exam results largely reflect intake.
3. So the honest description is **simultaneity, not one direction**. Both run at
   once, which is exactly why the literature leans so heavily on boundary
   discontinuities and natural experiments.

The gap between that and what you will read in the property press is large, and
worth understanding before doing any analysis — see "Beware the headline numbers".

## 1. Does school quality raise house prices?

### The founding method

**Black, S. (1999), "Do Better Schools Matter? Parental Valuation of Elementary
Education", *Quarterly Journal of Economics* 114(2), 577–599.**

The paper that created the standard design. Compares houses on either side of a
school attendance boundary, so neighbourhood, tax and spending differences are
held constant and only the school assignment changes. Finds parents pay **2.5%
more for a 5% increase in test scores**.

This "boundary discontinuity" approach is the reason the field is credible. A
naive comparison of good-school and bad-school areas measures the neighbourhood,
not the school.

### The English evidence

**Gibbons, S. & Machin, S. (2003), "Valuing English Primary Schools", *Journal of
Urban Economics* 53(2), 197–219.** First substantial UK application.

**Gibbons, S. & Machin, S. (2006), "Paying for Primary Schools: Admission
Constraints, School Popularity or Congestion?", *Economic Journal* 116(510).**

**Gibbons, S., Machin, S. & Silva, O. (2013), "Valuing School Quality Using
Boundary Discontinuities", *Journal of Urban Economics* 75, 15–28.**
[Working paper (CEE DP 132)](https://cep.lse.ac.uk/pubs/download/cee/ceedp132.pdf) ·
[Author copy](https://personal.lse.ac.uk/gibbons/papers/Valuing%20School%20Quality%20Using%20Discontinuity%20Final%20November%202012.pdf)

**This is the key paper for your question.** Uses a geographical boundary RD
across school attendance districts in England. Its contribution is separating
*school value-added* from *intake composition* — the first work to show
convincingly that parents pay for value-added specifically, not just for the
other people's children.

Headline: **a one-standard-deviation rise in either school value-added or pupil
prior achievement raises prices by around 3%.**

One finding matters enormously for anyone repeating this: **price effects from
age-7 achievement are entirely explained by pupil background characteristics**,
especially free school meal eligibility. In other words a large part of what
looks like a "good school premium" is a *composition* premium. If you regress
price on raw results, you are substantially measuring who lives there.

### Ofsted specifically — closest to your question

**Hussain, I. (University of Sussex), presented at the Royal Economic Society
annual conference, 2016.**
[RES media briefing](https://res.org.uk/mediabriefing/house-prices-rise-by-up-to-1-5-after-improved-ofsted-score-study-finds/)

Uses **Ofsted rating changes as an information shock** across ~8,000 English
primary schools — the design your question implies.

- A one-grade improvement raises local house prices by **~0.5% on average**
- **~1.5% in affluent neighbourhoods**
- **Essentially zero in deprived neighbourhoods**
- Symmetric: a downgrade deflates prices by a similar proportion
- **Short-term changes in exam results barely move prices at all**

That last point is the interesting one. Ofsted's letter grade appears to function
as a *salient, legible signal* in a way that underlying performance data does not.
The market responds to the label more than to the thing the label measures.

*Caveat: I could confirm the conference paper and its findings but not a
peer-reviewed journal version. Verify publication status before citing.*

### Grammar schools and selective systems

**Levon, K. et al. (2018), "The capitalisation of school choice into property
prices: A case study of grammar and all-ability state schools in Buckinghamshire",
*Geoforum*.** Finds premiums are higher where admission is more *probable*, not
just where the school is better — buyers price the odds of getting in. Houses in
multiple catchments command higher premiums, consistent with risk-spreading.

## 2. Does the housing market raise school results?

Yes, and mostly through a mechanism that is not about teaching.

Residence-based admission means school access is rationed by house price —
"selection by mortgage". That sorts higher-income families into particular
schools, and school results are strongly driven by intake. The chain is:

> house prices → who can live there → who attends → measured results

Which then feeds back into prices. This is a genuine simultaneous system.

Relevant strands:

- **Value-added vs raw results.** Raw attainment mostly reflects prior attainment
  and background; value-added measures attempt to strip that out. The IFS finds
  [parents — especially poorer ones — largely overlook value-added](https://ifs.org.uk/news/parents-especially-poorer-ones-overlook-value-added-when-applying-secondary-schools)
  when choosing schools, which means the market is partly capitalising the wrong
  signal.
- **Sorting and segregation.** Burgess, Allen and co-authors have a large body of
  work on how admission rules drive socio-economic and ethnic sorting in England.
  Distance-based ("proximity") admission produces *less* segregation than
  choice-based systems in several comparisons — see
  [Segregation by choice? School choice and segregation in England](https://www.tandfonline.com/doi/full/10.1080/09645292.2023.2181748).
- **Peer effects** provide the theoretical mechanism: if peers matter, residence-
  based assignment produces income sorting in equilibrium.

## 3. The natural experiment that matters most for us

**Brighton & Hove, 2007** — the local authority abolished proximity as the
tie-breaker and introduced a **lottery** within newly-drawn catchment areas,
explicitly to end selection by mortgage.

[Allen, Burgess & McKenna, CMPO working paper](https://www.bristol.ac.uk/media-library/sites/cmpo/migrated/documents/wp244.pdf) ·
[Bristol summary: "Catchment areas undermine hopes for Brighton lottery"](https://www.bristol.ac.uk/news/2010/7198.html)

**It largely failed to reduce socio-economic segregation.** Difference-in-
differences shows no significant change in sorting; point estimates if anything
suggest a slight *rise*.

Why: the lottery was run *within newly drawn geographic catchments*, so residence
still determined which lottery you entered. The reform changed the allocation
mechanism but not the geography.

**This is directly relevant to the boundary-redrawing hypothesis in the README.**
An authority that set out deliberately to break the house-price-to-school link,
with full legal power to do so, and redrew its catchments to achieve it, did not
move segregation. That is the closest thing to a direct test of the idea, and the
result was discouraging.

## 4. Beware the headline numbers

There is a large gap between credible causal estimates and property-industry
figures:

| Source type | Typical claimed premium |
|---|---|
| Boundary-discontinuity academic estimates | **2–4%** per SD of school quality |
| Ofsted rating-change estimates (Hussain) | **0.5–1.5%** per grade |
| DfE (2017) descriptive | 8% (best 10% primaries), 6.8% (secondaries) |
| Estate agent / PwC press releases | 10–50%, or £20k–£116k |

The agent figures are almost all **raw comparisons of catchment against
non-catchment**, with no attempt to hold the neighbourhood constant. They measure
the fact that nice areas contain good schools. Treat them as marketing, not
evidence — and expect any naive analysis of our own data to reproduce them.

## 5. What is left to do — where this project could contribute

The literature is mature, so the contribution has to be specific. Three
possibilities, in ascending order of strength:

**(a) Named catchments rather than inferred ones.** Much English work has to
approximate attendance areas from distance or LEA geography. North Yorkshire
publishes **explicit named catchment polygons**, which is a cleaner discontinuity
than most of the literature has had. Modest but real.

**(b) Price per m² rather than price.** The standard approach uses raw price with
hedonic controls. We have EPC floor areas matched to 96% of recent sales, so we
can work in £/m² directly and control composition much harder — the divide
analysis already showed that up to 58% of a raw price gap can be housing stock
rather than location.

**(c) Boundary *changes* as the identification — the strongest option.** North
Yorkshire alters catchments through annual consultation; the
[2023 Thirsk consultation](https://edemocracy.northyorks.gov.uk/documents/s27461/Appendix%208-%20Consultation%20on%20Thirsk%20School%20catchment%20area.html?CT=2)
moved three parishes into a joint catchment effective September 2025.

A boundary change **reassigns houses to a different school without changing the
houses, the neighbourhood, or the school**. That is a far cleaner experiment than
a cross-sectional boundary comparison, because it differences out everything
fixed about the location. If NYC's determination records give a usable history of
changes, a difference-in-differences on affected versus unaffected properties is
the best design available to us — and, notably, it is under-used in the English
literature relative to cross-sectional boundary RD.

The 20-year Price Paid panel already built here is exactly the right shape for it.

## 6. Methodological warnings, if we proceed

1. **Never regress price on raw exam results.** They encode intake. Use
   value-added, or the Ofsted-shock design, or both.
2. **Ofsted grades are not random.** Schools are inspected on a risk-based cycle,
   and inspection timing correlates with prior concerns. The Hussain design
   handles this by looking at the rating change at inspection; a naive
   cross-section will not.
3. **Sorting is the confounder and the outcome.** If prices rise after a good
   rating, richer families move in, results improve, and the rating is more likely
   to be maintained. Any long-run analysis is measuring a feedback loop.
4. **Catchment ≠ attendance.** Living outside a catchment does not prevent
   applying, and in-catchment does not guarantee a place. The treatment is a
   change in *probability* of admission, not a change in assignment.
5. **Our secondary layer is a stand-in.** The Ofsted question is most naturally
   asked of primaries — smaller catchments, sharper boundaries, and the Hussain
   result is primary-based. That needs the missing `.shp` from NYC.

## Sources

- [Black (1999), QJE — Do Better Schools Matter?](https://academic.oup.com/qje/article-abstract/114/2/577/1844232)
- [Gibbons, Machin & Silva (2013), JUE — Valuing School Quality Using Boundary Discontinuities](https://cep.lse.ac.uk/_new/publications/abstract.asp?index=7072)
- [Gibbons & Machin (2006), EJ — Paying for Primary Schools](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1468-0297.2006.01077.x)
- [Hussain (2016), RES conference — Ofsted and house prices](https://res.org.uk/mediabriefing/house-prices-rise-by-up-to-1-5-after-improved-ofsted-score-study-finds/)
- [Allen, Burgess & McKenna — early impact of Brighton & Hove's admission reforms](https://www.bristol.ac.uk/media-library/sites/cmpo/migrated/documents/wp244.pdf)
- [Bristol — Catchment areas undermine hopes for Brighton lottery](https://www.bristol.ac.uk/news/2010/7198.html)
- [Segregation by choice? School choice and segregation in England (2023)](https://www.tandfonline.com/doi/full/10.1080/09645292.2023.2181748)
- [IFS — Parents, especially poorer ones, overlook value added](https://ifs.org.uk/news/parents-especially-poorer-ones-overlook-value-added-when-applying-secondary-schools)
- [Capitalisation of school choice into property prices, Buckinghamshire (Geoforum)](https://www.sciencedirect.com/science/article/abs/pii/S0016718518302689)
- [DfE (2017) — House prices and schools](https://assets.publishing.service.gov.uk/media/5a82a832ed915d74e3402e69/House_prices_and_schools.pdf)
- [Fack & Grenet (2010), JPubE — Paris public and private schools](https://www.sciencedirect.com/science/article/abs/pii/S0047272709001388)
