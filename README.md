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
