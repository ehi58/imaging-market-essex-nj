# Imaging market study: Essex County, New Jersey, and the five counties around it

This is a reproducible pipeline that turns public Census and Medicare files into clean tables for a dashboard. It covers Essex, Bergen, Hudson, Morris, Passaic and Union counties, and measures:

- demand for imaging among residents 65 and over;
- where imaging providers are, and how much Medicare imaging is billed in the non-facility setting from each county;
- where the nursing homes that refer patients are;
- how much of all that lies within a 10-, 20- and 30-minute drive of three example sites.

**Rules this study keeps:**
- No company is named, ranked or recommended. Competitors appear only as counts and as map points that carry no name. Each point does carry registry flags, so it can be matched to a public registration (see Limitations).
- The three sites are examples of the method, not recommendations.
- No billing volume is published for any point, municipality or drive band. A county figure is published only when it passes the disclosure rule (see Method).
- A registered address is never read as a place served. Mobile and portable providers are shown at their registered address and are never counted by area or drive time.

The dashboard is not part of this repository. The tables in [`data/output/`](data/output) are built for Tableau or Power BI. [`data/README.md`](data/README.md) is their data dictionary.

## What it shows

| | finding (sources and limits below) |
|---|---|
| **Population** | 4,158,471 residents in 947 census tracts; **652,012 aged 65+** (ACS 2020–2024) |
| **Imaging use** | In 2024, Original Medicare beneficiaries had between **4,850 imaging events per 1,000 (Hudson) and 5,346 (Bergen)**; Essex had 5,253. Applied to every resident 65+, that is an index of about 3.37 million imaging events a year across the six counties |
| **Who that rate describes** | Original Medicare is under half of all beneficiaries in five of the six counties: Hudson 31.5%, Essex 35.7%, Passaic 38.1%, Union 38.5%, Bergen 49.9%; Morris is 53.4%. By CMS's own Medicare Advantage participation rate (MA ÷ Original Medicare + MA), MA is the majority in Hudson, Essex, Passaic and Union |
| **Competitors** | 124 imaging-center locations and 191 radiology-group offices (NPI registry, October 2026), plus 27 acute-care hospitals. Only 33 of the 124 imaging-center locations hold an NPI enrolled in Medicare in New Jersey. 49 mobile or portable locations are shown at their registered addresses and never counted by area |
| **Billed volume** | CY2024 Medicare Part B imaging services billed in the non-facility setting from addresses in each county: Bergen 328,257 · Essex 201,592 · Morris 142,559 · Union 138,230 · Passaic 104,839 · Hudson 50,191. Radiology billers alone: Bergen 86,310 · Essex 85,143 · Passaic 49,293 · Union 44,091 · Hudson 16,000 · Morris withheld under the disclosure rule. Modality splits are withheld for Morris, Passaic and Union |
| **Referral sources** | 139 certified nursing homes with 21,601 certified beds. Essex has the most beds per resident 65+ (40.5 per 1,000) and Hudson the fewest (26.8) |
| **Drive time** | Residents 65+ within 20 minutes of each example site: A (urban core) 293,156, or 45.0% of the study area; B (inner suburb) 227,004 (34.8%); C (outer suburb) 145,930 (22.4%). Imaging-center locations within the same 20 minutes: 61, 47 and 28. Free-flow times; see Limitations |

## Data

| source | vintage | used for |
|---|---|---|
| Census ACS 5-year table-based summary files B01001, B01003, B19013 | 2020–2024 | population, residents 65+, median household income by tract |
| Census Centers of Population by tract | 2020 | population-weighted tract centres (drive-time destinations) |
| Census cartographic boundary and TIGER/Line shapefiles (tracts, county subdivisions) | 2024 | land area, municipality assignment, GeoJSON for maps |
| Census county adjacency; ZCTA–county relationship file | 2024; 2020 | proving the study area; the list of study-area ZIPs |
| CMS Medicare Geographic Variation by National, State & County | 2024 | imaging events per 1,000 Original Medicare beneficiaries, by county and statewide by age |
| NPPES NPI registry, monthly V2 file | October 2026 release | imaging centers, radiology groups, mobile and portable providers, with practice locations |
| CMS Medicare Fee-For-Service Public Provider Enrollment (PECOS) | quarter from 2026-07-01 | Medicare enrollment flags (New Jersey enrollments only) |
| CMS Medicare Physician & Other Practitioners by Provider and Service | CY2024 | Part B imaging services by billing NPI |
| CMS Restructured BETOS Classification System (RBCS) | RY2026 file | which HCPCS codes are imaging, and the modality |
| CMS Care Compare: Nursing Home Provider Information; Hospital General Information | modified 2026-09-30; 2026-07-22 | nursing homes and beds; hospitals |
| Census Geocoder; OpenStreetMap Nominatim (fallback only); OSRM | October 2026 | coordinates and drive times |

The pipeline downloads everything and caches it in `data/raw/`, which is not committed. `controls.json` records the file names and release dates it used.

## Method

### Demand
- For each county, CMS's imaging events per 1,000 Original Medicare beneficiaries ("events in the Imaging category as defined by RBCS, per 1,000 OM beneficiaries") are multiplied by each tract's residents 65+.
- The result is an index, not a forecast. Every tract in a county gets that county's rate.

### Competitors
- **Selection.** Organisation NPIs whose registry entry carries one of these taxonomies (NUCC v26.1):
  - a fixed-site imaging taxonomy (radiology clinic, mammography, MRI center);
  - a radiology or nuclear-medicine physician taxonomy, which marks a radiology group;
  - a mobile or portable taxonomy (mobile radiology, mobile mammography, portable x-ray supplier).
- **Classes.** A fixed-site taxonomy wins over a mobile one.
- **Locations.** Primary and secondary practice locations are both used. Each address is geocoded and collapsed to one point per location and class, since one practice often holds several NPIs.
- **Flags.** Each point carries Medicare enrollment in New Jersey, enrollment as an IDTF or similar, and whether any of its NPIs appears in the CY2024 Part B file.
- **Precision.** Coordinates are rounded to three decimals, about 110 m.

### Volume
- **What is counted.** CY2024 Part B lines with an RBCS imaging code in the **non-facility** setting, placed at the billing address CMS prints for each NPI. Non-facility means offices, IDTFs and freestanding centers, but CMS also counts home and nursing-facility services there.
- **Excluded:**
  - facility-setting lines, which are almost all radiologists' reading fees for hospital exams billed from their group's address (929 billing NPIs in the study area);
  - mobile and portable billers, whose services happen elsewhere (9 billing NPIs);
  - drug and contrast lines, billed per mL or per dose (795 rows and 8.49 million units statewide).
- **Breakdown.** The figure is split by modality. A radiology-only subset covers diagnostic and interventional radiology, nuclear medicine and IDTFs.

### Disclosure rule
Volume is published **at county grain only**. A cell passes when all three hold:
- it has at least 3 billing NPIs;
- it has at least 3 distinct billing **sites**: geocoded points, with points closer than 75 m merged, so ten radiologists of one group, or one building geocoded two ways, count once;
- no site holds more than 60% of it;
- the two largest sites together hold no more than 80%, so the second-largest cannot subtract its own volume to learn the largest's.

On top of the cell test, a **row rule** applies, so no withheld value can be recovered by subtraction:
- The county total publishes only if it passes.
- The six modality cells publish all together or not at all. If any one fails, the hidden union is the whole total, which passed.
- The radiology figure publishes only if both it and everything else in the county pass.

`controls.json` records, per county, only *which* figures were withheld, and nothing that would bound one. Its only billed figure is the statewide count of drug and contrast units removed before any area exists. Where a county total is withheld, its biller and site counts are withheld too. The underlying CMS file is public: the rule governs what this study states, not what anyone could compute from the source. No point, municipality or drive band carries volume.

### Referral sources
Certified nursing homes, with certified beds per 1,000 residents 65+ and homes per square mile.

### Drive time
- OSRM road-network times from each example site to every tract's population-weighted centre, every fixed-site competitor point, hospital and nursing home.
- Coverage sums the tracts whose centre lies within 10, 20 and 30 minutes.

## Controls

The build runs every check **before it writes anything**. It writes to a staging folder and swaps it in whole, so a failed check, or a file locked by another program, leaves the previous outputs as they were. [`data/output/controls.json`](data/output/controls.json) records what each check saw and the SHA-256 of every file it wrote.

**Study area and population**
- The study area equals Essex plus every county the Census adjacency file lists as its neighbour.
- Tract population and residents 65+ sum exactly to the published county totals.
- Every populated tract has a polygon and a municipality.

**Enumerated lists are real**
Each configured value must occur before it is used, so a typo cannot silently admit nothing:
- every one of the 15 taxonomy codes (nationally);
- every PECOS imaging type;
- every RBCS imaging subcategory;
- the portable-supplier type;
- every radiology biller type;
- the hospital types.

**API pulls**
Every data.cms.gov pull must return fewer rows than the whole table, and every returned row must carry the filtered value. That API silently ignores a misspelled filter and returns the whole table.

**Geocoding**
- **Registry locations:** 90.2% Census-matched, 93.9% placed after the fallback.
- **Billed lines:** 97.1% located, weighted by billed count, among all lines billed from study-area ZIPs. The denominator comes from the Census ZIP–county file, not from what happened to geocode.
- **Hospitals and nursing homes:** every one in the study area agrees with the county CMS lists for it, checked in both directions.
- **Nursing-home agreement with CMS's own coordinates:** median 30 m.

**Drive times**
- Every destination routed.
- The worst snap to a road is 646 m, and 6 of 1,436 destinations sit more than 250 m away.
- Each site is closest to its own tract.

**Identities**
- Everything written, CSV, GeoJSON and controls.json alike, contains none of 2,459 organisation names (8 characters or longer) and none of 87,905 NPIs that the build read: registry, Part B and PECOS.
- The NPI check takes every 10-digit token in the output and intersects it with that set.
- The name check has one exemption, recorded by its Census code: a township that bills Medicare under its own place name.

**Tests**
`pytest` (13 tests) re-checks the committed tables against the manifest hashes and the controls:
- the disclosure row rule;
- that controls.json carries no volume figure beyond the two allowed statewide values;
- populations against the published ACS county totals;
- the demand rate against CMS's figures;
- coverage growing with each band;
- the absence of identifying columns.

## Limitations

**Demand**
- **The rate covers Original Medicare only.** It is applied to every resident 65+ as if Medicare Advantage members and people outside Medicare used imaging at the same rate. Original Medicare is under half of all beneficiaries in five of these counties.
- **The beneficiary counts don't add up to one total.** CMS counts some beneficiaries in neither Original Medicare nor MA: partial-year enrollees, and those with only Part A or only Part B. They are 16–21% of each county's total, and `counties.csv` carries them.
- **The county rows cover all ages,** including under-65 disabled beneficiaries. New Jersey's statewide 65+ rate is 1.95% higher than its all-ages rate (5,375.6 vs 5,272.7 per 1,000), so the index runs about 2% low for a 65+ population. That correction is a statewide figure and would differ by county.
- **Within a county every tract gets the same rate.** "Events" span all modalities, so the index is not demand for any one scanner.
- **ACS figures are 5-year estimates with margins of error.** Every table carries a margin for residents 65+. The demand index carries none.

**Competitors**
- **A registry listing is not an operating competitor.**
  - NPPES taxonomy is self-chosen and rarely removed. Of 124 imaging-center locations, 33 hold a Medicare-enrolled NPI, and 9 appear as a rendering NPI in the CY2024 Part B file, which itself drops provider–code rows under 11 beneficiaries.
  - Enrollment is checked against New Jersey enrollments only, so an NPI enrolled through another state shows as not enrolled.
  - Imaging done inside multi-specialty practices under other taxonomies is not counted as a location.
- **A radiology group's location is its registered office.** That is often a billing address, while its radiologists read at hospitals and centers elsewhere. The study counts offices; it does not claim reading capacity there.
- **Mobile and portable providers are kept apart only when their registry taxonomies are all mobile or portable.** An organisation carrying any fixed-site code is treated as fixed, for counting and for volume alike. So is a mobile IDTF without a mobile taxonomy. Its non-facility volume stays in the county where it is registered.
- **Hospitals are counts and points only.** CMS's outpatient-hospital file by provider carries comprehensive APCs only: 68 in New Jersey's rows, none of them imaging. Hospital technical imaging volume is therefore not public per hospital. `hospitals.csv` keeps every Care Compare type, including psychiatric, long-term and VA; counts and coverage use acute-care hospitals only.
- **Points can be located, by design.** Coordinates are rounded to about 110 m, and point drive times to whole minutes. Each competitor point still carries registry flags (NPI count, enrollment, PECOS type, Part B presence), so anyone can match it to its public registration. The study avoids naming and ranking; it does not hide where public registrations are. Nursing-home bed counts are Care Compare's own and identify the home; nursing homes are referral sources, not competitors.

**Volume**
- **The figures count billed services, not exams.**
  - The Part B file has no modifier field. A radiologist's reading of an exam done at an imaging center can be a non-facility line at the radiologist's address, while the center bills the technical part. One exam can therefore count twice, in different places.
  - The volume is Medicare fee-for-service Part B only, for CY2024. Medicare Advantage, Medicaid and commercial volume are invisible, and CMS drops provider–code rows under 11 beneficiaries.
  - The billing address is the one CMS prints for the NPI's data year. For a group it can be a central office.
  - "All billers" includes in-office imaging by ophthalmology, cardiology, orthopedics, urology and others. The radiology figure isolates radiology billers.
  - Three NPIs at three sites can still be one company with three offices. The site and dominance rules reduce the risk; they cannot rule it out.

**Geography**
- **The study area stops at the six counties.** Competitors and residents in Manhattan, Staten Island, Rockland, Middlesex, Somerset, Sussex and Warren lie outside it, though some sit inside the 30-minute bands. Bands near the edge undercount.
- **Drive times are free-flow.** There is no traffic and no time of day; times come from OpenStreetMap through the public OSRM demo server. Peak-hour times here are substantially longer. Destinations are tract population centres, not every address.
- **Municipal ratios mix two methods.** Municipal population comes from assigning each tract whole to the municipality holding its population centre, while points are placed by polygon. Four municipalities receive no tract: Rockleigh, Teterboro, Victory Gardens and Mendham Township (17.8 sq mi). They have rows with zero population but carry their points.
- **Geocoding failures are not random.**
  - Campus and single-site addresses fail most often.
  - Fallbacks placed 25 registry addresses, 113 billing addresses and 12 hospital addresses. 13 nursing homes use CMS's own coordinates.
  - What still failed is left out: 6.1% of registry location rows, and 2.9% of billed services in study-area ZIPs.

**Other**
- **The sources have different dates:** NPPES October 2026, PECOS mid-2026, billing CY2024, ACS 2020–2024, Care Compare 2026.
- **Nursing homes are one kind of referral source.** Physicians, urgent care, assisted living and home health are not counted.

## Certificate of need, New Jersey (as of October 2026)

**No certificate of need is required to establish MRI or CT** in a freestanding or ambulatory imaging center, or in a physician's private practice. In a hospital it is not required for MRI, and almost certainly not for CT. **A license is required:** any entity providing MRI or CT, physicians included, must hold a New Jersey Department of Health license before it starts.

- **Statute.** N.J.S.A. 26:2H-7a exempts "Ambulatory care facilities" and "Magnetic resonance imaging" from the certificate-of-need requirement. That is the current text, reprinted in a 2026 Assembly bill whose cross-reference shows it was last amended in 2021.
- **Rule.** N.J.A.C. 8:33's list of services that need a certificate contains no imaging. Its review table marks MRI and PET "Exempt", and it defines "major moveable equipment" as cardiac catheterization equipment only (8:33-1.3, App. A).
- **Licence.** N.J.S.A. 26:2H-12(f), added by P.L.2004 c.54: an entity providing "magnetic resonance imaging or computerized axial tomography services shall be required to obtain a license from the department … prior to commencement of services". The ambulatory-care rule N.J.A.C. 8:43A names CT and MRI. The fee is $4,000 to apply or renew, plus $2,000 in an inspection year (8:43A-2.2).
- **The unclear part is CT in hospitals.** CT is never named in an exemption. The statute still lists "major moveable equipment whose total cost is over $2 million" as a trigger, while the rule narrows that term to cardiac catheterization. No Department source applies the $2 million clause to CT, and none rules it out either.
- **Self-referral.** New Jersey's self-referral law (the Codey Law, N.J.S.A. 45:9-22.5) bars referral to an imaging service in which the physician holds a significant beneficial interest. It has an in-office exception. Whether a given arrangement qualifies is a question for counsel.

This is research from public sources, not legal advice. Several statute texts were read on unofficial hosts current to January 2024.

## Reproduce it

```
python -m venv .venv
.venv\Scripts\activate                 # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m market_study.build --nppes-zip PATH   # reuse a downloaded NPPES monthly V2 file
python -m market_study.build                    # or let it download the current month (1.1 GB)
pytest
```

**When a re-run reproduces the outputs:**
- **With the same `--nppes-zip` file and the `data/raw/` cache in place,** a re-run reads everything from the cache and reproduces the outputs exactly.
- **Without `--nppes-zip`,** the build checks the NPPES download page and uses the current month's file, so competitor counts move from month to month.
- **Deleting `data/raw/`** re-pulls every source at its current release.

## Layout

```
src/market_study/config.py      study area, example sites, taxonomies, disclosure thresholds, source URLs
src/market_study/sources.py     one reader per public source
src/market_study/fetch.py       cached downloads; data.cms.gov pulls that refuse an unfiltered result
src/market_study/geo.py         Census batch geocoder, Nominatim fallback, polygons, GeoJSON
src/market_study/drivetime.py   OSRM table requests, cached
src/market_study/build.py       the pipeline, its controls and the disclosure rule
data/output/                    the dashboard tables, GeoJSON and controls.json
data/README.md                  data dictionary
tests/test_outputs.py           checks on the committed tables
```

## Licence

The code is MIT-licensed (see [`LICENSE`](LICENSE)). The tables in `data/output/` derive from U.S. Government works published by the Census Bureau and the Centers for Medicare & Medicaid Services. They also use OpenStreetMap data (© OpenStreetMap contributors, ODbL) for drive times and for fallback locations.
