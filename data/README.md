# Output tables: data dictionary

## Format and loading

- Every table in `output/` is a CSV: header row, UTF-8, LF line endings. `.gitattributes` keeps git from converting them, which would break the hash check.
- Keys are text. Keep their leading zeros when loading: `tract_geoid` (11 digits), `county_fips` (5), `municipality_geoid` (10).
- `raw/` holds downloads and API caches. It is not committed; `python -m market_study.build` recreates it.

## What the tables never contain

No table contains a company name, an NPI, a street address, a phone number or a CMS certification number. The build checks the written text against every organisation name and NPI it read before it writes anything; see `controls.json`, keys `no_organisation_name_in_any_output` and `no_npi_in_any_output`.

Point IDs (`L0001`, `H001`, `N001`) are sequential labels for one build. They are not stable across builds and do not identify anything.

**No billing volume appears below county grain.**

## Joins for a dashboard

| join | from | to |
|---|---|---|
| tracts to map | `tracts.tract_geoid` | `geo/study_tracts.geojson` → `tract_geoid` |
| municipalities to map | `municipalities.municipality_geoid` | `geo/study_municipalities.geojson` → `municipality_geoid` |
| points to areas | each points table's `lat`/`lon` | `tract_geoid`, `county_fips`, `municipality_geoid` on the same row |

## tracts.csv: one row per 2020 census tract in the six counties

| column | meaning |
|---|---|
| tract_geoid, county_fips, county_name | the 2020 tract and its county |
| municipality_geoid, municipality | the county subdivision containing the tract's population-weighted centre. A tract crossing a municipal line is assigned whole |
| pop_total, pop_total_moe | ACS 2020–2024 5-year total population (B01003), with its 90% margin of error |
| pop_65plus, pop_65plus_moe | residents 65 and over: the sum of 12 B01001 age-by-sex cells. The MOE is the root-sum-of-squares approximation |
| median_hh_income, median_hh_income_moe | B19013, 2024 dollars |
| land_sqmi | land area from the Census cartographic boundary file |
| centroid_lat, centroid_lon | 2020 population-weighted tract centre |
| county_om_imaging_events_per_1000 | the county's 2024 imaging events per 1,000 Original Medicare beneficiaries, all ages (CMS Geographic Variation). **Every tract in a county carries the same value** |
| est_imaging_events_65plus | pop_65plus × that rate ÷ 1,000. A demand index, not a forecast |
| drive_min_A/B/C | free-flow drive minutes from each example site to the tract centre (OSRM) |
| drive_min_nearest_site, nearest_site | the smallest of the three, and which site it is |

## counties.csv: one row per county

| column | meaning |
|---|---|
| tracts, pop_total, pop_65plus, pop_65plus_moe, pct_65plus, land_sqmi, est_imaging_events_65plus | sums over the county's tracts |
| imaging_center_locations | fixed-site imaging-center locations (see `competitor_locations.csv`) |
| radiology_group_offices | registered offices of radiology groups |
| acute_care_hospitals, other_hospitals | Care Compare hospitals; "other" covers psychiatric, long-term and VA |
| nursing_homes, nursing_home_beds | certified nursing homes and their certified beds |
| nursing_home_beds_per_1000_65plus, nursing_homes_per_sqmi | referral-source density |
| imaging_center_locations_per_100k_65plus | imaging-center locations per 100,000 residents 65+ |
| medicare_benes_2024, original_medicare_benes_2024, medicare_advantage_benes_2024 | CMS Geographic Variation 2024 counts |
| neither_om_nor_ma_benes_2024 | total minus Original Medicare minus MA: partial-year, Part A-only or Part B-only beneficiaries |
| original_medicare_share_of_all | original_medicare ÷ total |
| ma_participation_rate | CMS's own rate: MA ÷ (Original Medicare + MA) |
| om_benes_using_imaging_pct, om_imaging_events_per_1000_benes, om_imaging_std_payment_per_capita | 2024 imaging use by Original Medicare beneficiaries |
| nonfacility_billing_npis, nonfacility_billing_sites | distinct NPIs, and distinct billing sites (geocoded points, merged within 75 m), behind the non-facility volume. Blank where the total is withheld |
| nonfacility_imaging_svcs | CY2024 Part B imaging services in the non-facility setting (offices, IDTFs, freestanding centers, and also home and nursing-facility services), billed by any NPI, individual or organisation, whose billing address is in the county. Excludes facility-setting lines, mobile and portable billers, and drug and contrast lines. These are billed services, not exams |
| nonfacility_radiology_svcs | the same, for diagnostic and interventional radiology, nuclear medicine and IDTF billers only |
| nonfacility_svcs_ct_scan, nonfacility_svcs_magnetic_resonance, nonfacility_svcs_nuclear, nonfacility_svcs_standard_x_ray, nonfacility_svcs_ultrasound, nonfacility_svcs_imaging_miscellaneous | nonfacility_imaging_svcs by RBCS imaging subcategory. They publish all six or none, and when published they sum to nonfacility_imaging_svcs |

**Blank volume cells are withheld under the disclosure rule.** A cell needs at least 3 NPIs and 3 billing sites, with no site over 60% and the top two sites at no more than 80%. On top of that, the row rule hides all six modality cells if any one fails, and hides radiology unless both it and the rest of the county pass (see the main README). `controls.json` → `volume_withheld` records only which figures were withheld, never why in a way that would bound them.

## municipalities.csv: one row per county subdivision (180)

- The columns are the same population, competitor, hospital and nursing-home columns as `counties.csv`, without any Medicare or volume column.
- `land_sqmi` is the municipality's own land area.
- Points are placed by polygon. Population comes from the tract assignment above.
- Four municipalities have no tract centre and show zero population: Rockleigh, Teterboro, Victory Gardens and Mendham Township.

## competitor_locations.csv: one row per distinct location per class

| column | meaning |
|---|---|
| location_id | sequential label |
| class | one of three (NUCC codes below) |
| registered_address_only | TRUE for `mobile_or_portable`. These rows have no drive times and are never counted by area |
| n_npis | organisation NPIs registered at this location in this class |
| lat, lon | geocoded practice location, rounded to 3 decimals (about 110 m) |
| tract_geoid, county_fips, county_name, municipality_geoid, municipality | where the point falls |
| medicare_enrolled_nj | any NPI here appears in the Medicare public enrollment file for New Jersey (quarter from 2026-07-01) |
| pecos_imaging_type | IDTF / portable x-ray supplier / mammography center, where enrolled as such |
| in_cy2024_part_b_file | any NPI here appears as a rendering NPI in the CY2024 Part B by-provider-and-service file. Provider–code rows under 11 beneficiaries are suppressed by CMS |
| location_source | `primary` (NPPES practice location) and/or `secondary` (NPPES secondary practice location) |
| drive_min_A/B/C | free-flow drive minutes from each example site, in whole minutes (fixed-site classes only) |

**Classes and their NUCC codes:**

| class | codes | meaning |
|---|---|---|
| `imaging_center` | 261QR0200X, 261QR0206X, 261QM1200X | fixed-site imaging center |
| `radiology_group` | radiology or nuclear-medicine physician taxonomies | radiology group; the point is its registered office |
| `mobile_or_portable` | 261QR0207X, 261QR0208X, 335V00000X | mobile or portable provider; a fixed-site code wins if both appear |

## hospitals.csv: one row per hospital in the six counties

| column | meaning |
|---|---|
| hospital_id | sequential label |
| hospital_type, is_acute_care, emergency_services | from Care Compare (July 2026) |
| lat, lon | 3 decimals |
| geocode_source | `census_geocoder`, or `osm_nominatim` for campus addresses the Census geocoder could not match |
| tract_geoid, area keys | where the point falls |
| drive_min_A/B/C | free-flow drive minutes from each example site, in whole minutes |

There is no volume column: CMS does not publish hospital outpatient imaging per hospital.

## nursing_homes.csv: one row per certified nursing home in the six counties

| column | meaning |
|---|---|
| nursing_home_id | sequential label |
| certified_beds | from Care Compare (September 2026) |
| lat, lon | 3 decimals |
| geocode_source | `census_geocoder`, or `cms_coordinates` where it had no match |
| tract_geoid, area keys | where the point falls |
| drive_min_A/B/C | free-flow drive minutes from each example site, in whole minutes |

## sites.csv and site_coverage.csv

- **`sites.csv`** holds the three example sites: illustrations, not recommendations.
- **`site_coverage.csv`** has one row per site per drive band (10, 20 and 30 minutes). Population figures cover tracts whose centre is within the band; nursing homes, hospitals and competitor locations are counted by each point's own drive time:
  - population and residents 65+, with MOE and share of the study area;
  - the demand index;
  - nursing homes and beds;
  - acute-care hospitals;
  - imaging-center locations and radiology-group offices, and imaging-center locations per 100,000 residents 65+.
  - It has no volume and no mobile or portable providers.

## controls.json

- Every check the build ran, with what it saw. The build stops before writing on any failure and swaps the output folder in whole, so these files are the ones `controls.json` vouches for. `manifest_sha256` gives each file's hash, and `pytest` re-checks them and fails on any file outside the manifest.
- It also records:
  - geocoding and fallback counts;
  - everything excluded from volume, with its reason (NPI counts; the one statewide figure is the drug and contrast units removed before any area exists);
  - the biller types inside the non-facility volume, as NPI counts;
  - which county volume figures were withheld (`volume_withheld`);
  - the statewide imaging rate by age;
  - the finding that hospital outpatient imaging is not published per hospital;
  - source files and release dates.
