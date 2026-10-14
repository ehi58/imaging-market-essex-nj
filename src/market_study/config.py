"""Study definition. Everything a reader might want to change lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"          # downloads; never committed
OUT = ROOT / "data" / "output"       # dashboard tables; committed

STATE_FIPS = "34"
STATE_ABBR = "NJ"
FOCUS_COUNTY = "34013"
# Essex County plus every county that shares a border with it. build.py checks this
# set against the Census county adjacency file and stops if they disagree.
COUNTIES = {
    "34013": "Essex",
    "34003": "Bergen",
    "34017": "Hudson",
    "34027": "Morris",
    "34031": "Passaic",
    "34039": "Union",
}

# Three EXAMPLE candidate sites. Coordinates near municipal centres, chosen to show an
# urban core, an inner suburb and an outer suburb. They are illustrations of the method,
# not recommendations, and no business or property is implied.
SITES = [
    {"site_id": "A", "label": "Example site A (urban core, Newark)", "lat": 40.7357, "lon": -74.1724},
    {"site_id": "B", "label": "Example site B (inner suburb, Bloomfield)", "lat": 40.8068, "lon": -74.1854},
    {"site_id": "C", "label": "Example site C (outer suburb, Livingston)", "lat": 40.7959, "lon": -74.3149},
]
DRIVE_BANDS_MIN = [10, 20, 30]

# NUCC taxonomy v26.1. Organisations (entity type 2) only: the study counts places and
# groups, not individual clinicians.
#
# Fixed-site imaging centers. Mobile and portable taxonomies are kept apart: their registered
# address is an office, not where the work happens, so they are never counted by area or
# drive band (the market-data rule: a registered address is not a service area).
IMAGING_CENTER_TAXONOMY = {
    "261QR0200X": "radiology clinic/center",
    "261QR0206X": "mammography",
    "261QM1200X": "MRI center",
}
MOBILE_OR_PORTABLE_TAXONOMY = {
    "261QR0207X": "mobile mammography",
    "261QR0208X": "radiology, mobile",
    "335V00000X": "portable x-ray supplier",
}
RADIOLOGY_GROUP_TAXONOMY = {
    "2085R0202X": "diagnostic radiology",
    "2085R0204X": "vascular & interventional radiology",
    "2085N0700X": "neuroradiology",
    "2085B0100X": "body imaging",
    "2085U0001X": "diagnostic ultrasound",
    "2085P0229X": "pediatric radiology",
    "2085N0904X": "nuclear radiology",
    "2085D0003X": "diagnostic neuroimaging",
    "207U00000X": "nuclear medicine",
}
# Classes that may be counted by area and drive band.
AREA_CLASSES = ("imaging_center", "radiology_group")
ACUTE_HOSPITAL_TYPES = {"Acute Care Hospitals"}
RADIOLOGY_BILLER_TYPES = {"Diagnostic Radiology", "Interventional Radiology", "Nuclear Medicine",
                          "Independent Diagnostic Testing Facility (IDTF)"}
# Points are published at 3 decimals (about 110 m north-south here): enough for a county map.
POINT_DECIMALS = 3

# Medicare provider-type codes in the public enrollment file (PECOS).
PECOS_IMAGING_TYPES = {"12-47": "IDTF", "12-63": "portable x-ray supplier", "12-45": "mammography center"}

# Disclosure rule for billing volume. A published cell needs at least this many distinct
# billing NPIs AND distinct billing addresses (ten radiologists of one group at one office are
# ten NPIs but one address), and no single address may hold more than MAX_TOP_SHARE of it.
# Volume is published at county grain only, with complementary suppression.
MIN_BILLERS_FOR_VOLUME = 3
MAX_TOP_ADDRESS_SHARE = 0.60
# ...and the top two sites together may hold at most this share, so the second-largest site
# cannot subtract its own volume from a published figure to learn the largest one's.
MAX_TOP_TWO_SHARE = 0.80
# Billing points within this distance are one site (one building, two spellings or two geocoders).
SITE_MERGE_METERS = 75

# CMS data.cms.gov dataset UUIDs (latest versions as of 2026-10-14).
CMS = {
    "pecos_enrollment": "2457ea29-fc82-48b0-86ec-3b0755de7515",       # 2026-07-01 quarter
    "pop_provider_service": "92396110-2aed-4d63-a6a2-5d6207d46a29",   # CY2024
    "opps_provider_service": "ccbc9a44-40d4-46b4-a709-5caa59212e50",  # CY2024
    "geo_variation": "6219697b-8f6c-4164-bed4-cd9317c58ebc",          # 2014-2024
}
RBCS_CSV = "https://data.cms.gov/sites/default/files/2026-09/c35bb6b7-501d-4c27-ae29-514386dc8919/RBCS_Taxonomy_Final_RY26_20260731.csv"
CARE_COMPARE = {"nursing_homes": "4pq5-n9py", "hospitals": "xubh-q36u"}

ACS_YEAR = 2024  # 2020-2024 5-year estimates
ACS_SF = "https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-{table}.dat"
CENPOP_TRACTS = "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR34.txt"
COUNTY_ADJACENCY = "https://www2.census.gov/geo/docs/reference/county_adjacency/county_adjacency2024.txt"
TRACT_SHP = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_34_tract_500k.zip"
COUSUB_SHP = "https://www2.census.gov/geo/tiger/TIGER2024/COUSUB/tl_2024_34_cousub.zip"
COUSUB_DISPLAY_SHP = "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_34_cousub_500k.zip"
GEOCODER_BATCH = "https://geocoding.geo.census.gov/geocoder/geographies/addressbatch"
OSRM_TABLE = "https://router.project-osrm.org/table/v1/driving/"
NPPES_INDEX = "https://download.cms.gov/nppes/NPI_Files.html"
ZCTA_COUNTY_REL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt"
GV_STATE_DESC = "NJ"
