# fwh_road_safety

US fatal-crash **rate** by state: NHTSA FARS fatalities over FHWA vehicle-miles
travelled.

> ⚠️ **This is a fatal-crash measure, not a "dangerous roads" measure.** FARS
> records fatal crashes only. Fatal crashes concentrate on high-speed rural
> roads; injury crashes concentrate on urban arterials, so this and a high-injury
> network disagree almost everywhere.

## Why the rate, not the count

A raw fatal-crash count map is a population map with extra steps — it ranks
California, Texas and Florida first because that is where the driving happens.
Dividing by exposure reorders it completely:

| | leaders |
|---|---|
| count | California, Texas, Florida |
| **rate per 100M VMT** | **Mississippi 1.79, Arizona 1.74, South Carolina 1.72** |
| lowest rate | Massachusetts 0.56, Minnesota 0.69, New Jersey 0.78 |

Validated against the published figure: the pipeline computes a national rate of
**1.26 deaths per 100M VMT** for 2023, which is what NHTSA reports.

## FFL at a glance

```ffl
crashes = roadsafety.source.FARS(year = 2023, dest = "/data/fars")
vmt     = roadsafety.source.VMT(year = 2023, dest = "/data/vmt")
rates   = roadsafety.StateRates(crashes_path = crashes.crashes_path,
                                vmt_path = vmt.vmt_path, dest = "/data/rates.json")
map     = roadsafety.RateMap(rates_path = rates.rates_path,
                             geometry_url = CB_STATES, dest = "/data/map.html")
```

Run the whole thing: `roadsafety.FatalCrashRateByState`.

## Things this gets right on purpose

**The coordinate sentinels.** FARS codes an unknown location as a run of 7s, 8s
or 9s rather than leaving it blank. They parse as valid floats — 77.7777 N is in
the Arctic Ocean. 129 of 37,769 crashes (0.34%) in 2023. ⚠️ But a sentinel must
also be *geographically impossible*: longitude −77.7777 is a real place on the
Carolina coast, and matching on magnitude alone discarded 4 genuine crashes. The
crash is still counted — it lost its location, not its death.

**The uncertainty.** Each state carries a Poisson 95% interval, because a rate
built on 342 deaths (Massachusetts) is not comparable to one built on 4,294
(Texas), and a choropleth invites exactly that comparison.

**The key space.** Only states present in *both* sources are rated, and the
number dropped is reported. FARS carries territory codes that VM-2 does not;
mixing them puts a numerator over one key space and a denominator over another.

**The file version.** ⚠️ FARS is *revised after publication*. The 2023 file
downloaded in this repo contains **41,025** fatalities; NHTSA's headline for 2023
is **40,901**. Both `accident.FATALS` and `person.INJ_SEV=4` in that file agree
on 41,025, so it is a later revision, not a parse error. The workflow writes a
`fw.provenance` manifest recording which download produced a given result.

## County: deaths per 100,000 residents

A **different measure**, not a finer-grained one. Per-VMT answers "how deadly per
unit of travel"; per-capita answers "how deadly for the people who live here".
County VMT is not published, so this uses the denominator that exists — and says
so.

⚠️ **Population is a poor proxy for exposure in small counties.** Median rate by
county size, 2019–2023:

| county population | median deaths / 100k / yr |
|---|---|
| under 5,000 | **200.4** |
| 5,000–25,000 | 33.4 |
| 25,000–100,000 | 18.0 |
| 100,000–500,000 | 11.6 |
| over 500,000 | **8.3** |

A 24× spread. Rural residents are not dying 24× more often per mile driven; they
live where other people's driving happens. Loving County, Texas tops the raw list
at **9,767 per 100k** from 21 deaths among 43 residents — and it *passes* the
NCHS reliability threshold, which is the point: the ≥20-event rule does not
rescue a per-capita denominator on a through-traffic county.

⚠️ **Pooling years is not cosmetic.** On one year only **15%** of counties reach
20 deaths; over five years, **62%** do. Counties below the threshold are drawn
hatched rather than dropped, because a blank county reads as missing data rather
than as a small number.

⚠️ **Connecticut is excluded** (1,426 crash records). FARS still codes it with
the 8 legacy counties; the Census 2023 vintage uses 9 planning regions. The
overlap is **empty**, so a silent join blanks the state out — and the legacy
counties do not aggregate cleanly into the new regions, because towns were
reassigned.

⚠️ **A UTF-8 BOM silently zeroed a whole year.** The 2022 national file begins
with `EF BB BF`; decoded as latin-1 the first column name is no longer `STATE`,
every row lookup raises `KeyError`, and a parser that skipped bad rows returned
**zero crashes from a 24 MB file while reporting success** — 39,422 crashes and
42,721 deaths lost in silence. Now decoded `utf-8-sig` first, and an all-rows-
skipped parse raises instead of returning empty.

## Not in v1

- **County and segment geography.** County VMT is not published as a standard
  table; it needs HPMS aggregation. Segment rates need map-matching crashes onto
  OSM, twice over (once for crashes, once for AADT).
- **Injury crashes.** State systems (e.g. California SWITRS via TIMS) add injury
  and sometimes property-damage records. That is what turns this into a
  high-injury network.
- **The risk tier.** "The rate is high *after accounting for road type*, and the
  uncertainty is small enough to say so." Most segments have zero or one fatal
  crash, which is why the Highway Safety Manual uses Empirical Bayes rather than
  observed rates.

## Sources

- [NHTSA FARS](https://www.nhtsa.gov/research-data/fatality-analysis-reporting-system-fars)
- [FHWA Highway Statistics VM-2](https://www.fhwa.dot.gov/policyinformation/statistics/2023/vm2.cfm)
- [Census cartographic state boundaries](https://www2.census.gov/geo/tiger/GENZ2023/)
