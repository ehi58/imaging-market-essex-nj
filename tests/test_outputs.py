"""Checks on the committed output tables. They read data/output only, so they run on a fresh
clone without re-downloading anything. A missing output fails; nothing here skips."""
import hashlib
import json
import re

import pandas as pd
import pytest

from market_study import config as C

OUT = C.OUT
TABLES = ["tracts.csv", "counties.csv", "municipalities.csv", "competitor_locations.csv", "hospitals.csv",
          "nursing_homes.csv", "sites.csv", "site_coverage.csv"]
KEYS = {"tract_geoid": str, "county_fips": str, "municipality_geoid": str}


@pytest.fixture(scope="module")
def controls():
    return json.loads((OUT / "controls.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def t():
    return {n: pd.read_csv(OUT / n, dtype=KEYS) for n in TABLES}


def test_files_are_the_ones_the_controls_vouch_for(controls):
    manifest = controls["manifest_sha256"]
    assert set(TABLES) <= set(manifest)
    for name, digest in manifest.items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == digest, name
    on_disk = {p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file()}
    assert on_disk == set(manifest) | {"controls.json"}, on_disk ^ (set(manifest) | {"controls.json"})


def test_every_output_has_rows(t):
    floors = {"tracts.csv": 800, "counties.csv": 6, "municipalities.csv": 180, "competitor_locations.csv": 50,
              "hospitals.csv": 10, "nursing_homes.csv": 100, "sites.csv": 3, "site_coverage.csv": 9}
    for n, floor in floors.items():
        assert len(t[n]) >= floor, (n, len(t[n]))


def test_every_build_control_passed(controls):
    gated = {k: v for k, v in controls.items() if isinstance(v, dict) and "passed" in v}
    assert len(gated) >= 25, sorted(gated)
    assert not [k for k, v in gated.items() if not v["passed"]]


def test_identity_checks_actually_looked(controls):
    assert controls["no_organisation_name_in_any_output"]["names_checked"] > 500
    assert controls["no_npi_in_any_output"]["npis_checked"] > 50_000


def test_no_identifying_columns(t):
    banned = re.compile(r"name$|^npi|address|street|phone|ccn|facility_id|legal|zip", re.I)
    allowed = {"county_name", "municipality", "registered_address_only"}
    for n, df in t.items():
        assert not [c for c in df.columns if banned.search(c) and c not in allowed], n


def test_points_sit_in_the_study_area(t):
    for n in ("tracts.csv", "competitor_locations.csv", "hospitals.csv", "nursing_homes.csv"):
        assert t[n].county_fips.notna().all(), n
        assert set(t[n].county_fips) <= set(C.COUNTIES), n
    for n in ("competitor_locations.csv", "hospitals.csv", "nursing_homes.csv"):
        df = t[n]
        assert df.municipality_geoid.notna().all(), n
        assert (df.lat.round(C.POINT_DECIMALS) == df.lat).all() and (df.lon.round(C.POINT_DECIMALS) == df.lon).all(), n
        d = df[[f"drive_min_{s}" for s in "ABC"]]
        assert ((d.round(0) == d) | d.isna()).all().all(), n


def test_no_volume_below_county_grain(t):
    for n in ("municipalities.csv", "competitor_locations.csv", "hospitals.csv", "nursing_homes.csv", "site_coverage.csv", "tracts.csv"):
        assert not [c for c in t[n].columns if "svcs" in c], n


# The only figures allowed: one statewide count of drug/contrast units removed before any area
# exists, and the located share (a ratio of two unpublished amounts over a different population).
ALLOWED_FIGURES = {"/excluded_drug_and_contrast_lines/units",
                   "/study_zcta_lines_located_floor/located_share_weighted_by_billed_count"}


def test_controls_carry_no_volume_figure(controls):
    found = []

    def walk(o, path):
        if isinstance(o, dict):
            for k, v in o.items():
                p = path + "/" + k
                if (re.search(r"svcs|srvcs|services|units|volume|share|payment|allowed", k, re.I)
                        and isinstance(v, (int, float)) and not isinstance(v, bool) and p not in ALLOWED_FIGURES):
                    found.append(p)
                walk(v, path + "/" + k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")
    walk(controls, "")
    assert not found, found


def test_modality_cells_are_all_or_none(t, controls):
    co = t["counties.csv"]
    mods = [c for c in co.columns if c.startswith("nonfacility_svcs_")]
    assert len(mods) == 6, mods
    for _, r in co.iterrows():
        hidden = r[mods].isna().sum()
        assert hidden in (0, 6), r.county_fips
        if hidden == 0:
            assert abs(r[mods].sum() - r.nonfacility_imaging_svcs) < 1e-6
        if pd.isna(r.nonfacility_imaging_svcs):
            assert hidden == 6 and pd.isna(r.nonfacility_radiology_svcs)
            assert pd.isna(r.nonfacility_billing_npis) and pd.isna(r.nonfacility_billing_sites)
        w = controls["volume_withheld"][r.county_fips]
        assert w["modalities"] == (hidden == 6) and w["radiology"] == pd.isna(r.nonfacility_radiology_svcs)
        assert w["total"] == pd.isna(r.nonfacility_imaging_svcs)


def test_mobile_and_portable_never_counted_by_area(t):
    loc = t["competitor_locations.csv"]
    mob = loc[loc["class"] == "mobile_or_portable"]
    assert mob.registered_address_only.all()
    assert mob[[f"drive_min_{s}" for s in "ABC"]].isna().all().all()
    for n in ("counties.csv", "municipalities.csv", "site_coverage.csv"):
        assert not [c for c in t[n].columns if "portable" in c or "mobile" in c], n
    co = t["counties.csv"]
    assert co.imaging_center_locations.sum() == (loc["class"] == "imaging_center").sum()
    assert t["municipalities.csv"].nursing_homes.sum() == len(t["nursing_homes.csv"]) == co.nursing_homes.sum()


def test_population_matches_published_acs_county_totals(t, controls):
    published = controls["acs_tracts_sum_to_county"]["published_county"]
    co = t["counties.csv"].set_index("county_fips")
    for fips, v in published.items():
        assert co.at[fips, "pop_65plus"] == v["pop_65plus"]
        assert co.at[fips, "pop_total"] == v["pop_total"]


def test_demand_rate_is_the_cms_county_rate(t, controls):
    gv = controls["county_inputs"]["geo_variation"]
    tr = t["tracts.csv"]
    for fips, v in gv.items():
        assert (tr.loc[tr.county_fips == fips, "county_om_imaging_events_per_1000"] == v["om_imaging_events_per_1000_benes"]).all()


def test_drive_times_are_plausible(t):
    tr = t["tracts.csv"]
    for s in "ABC":
        col = f"drive_min_{s}"
        assert tr[col].notna().mean() > 0.99
        assert tr[col].min() < 5 and tr[col].max() < 120
        c = t["site_coverage.csv"]
        assert c[c.site_id == s].sort_values("band_min").pop_65plus.is_monotonic_increasing
