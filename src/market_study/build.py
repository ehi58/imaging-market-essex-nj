"""Build every dashboard table from public sources.

    python -m market_study.build [--nppes-zip PATH]

Writes data/output/*.csv, data/output/geo/*.geojson and data/output/controls.json.
Every control that fails stops the build BEFORE anything is written, so the files in
data/output are always the ones controls.json vouches for (it carries their SHA-256).
"""
import argparse
import hashlib
import json
import re

import numpy as np
import pandas as pd

from . import config as C
from . import sources as S
from .drivetime import table as osrm_table
from .fetch import download
from .geo import PolygonIndex, geocode, geojson_text, haversine_km, nominatim, read_polygons

CONTROLS: dict = {}


def control(name, ok, **seen):
    CONTROLS[name] = {"passed": bool(ok), **seen}
    if not ok:
        raise SystemExit(f"CONTROL FAILED: {name} {seen}")


def addr_id(*parts):
    return hashlib.sha256("|".join(str(p).upper().strip() for p in parts).encode()).hexdigest()[:16]


def place_with_fallback(df, street, city, zip5, retry_zip, tract_idx, label):
    """Census batch geocode; unmatched addresses whose ZIP passes retry_zip retry via Nominatim."""
    df = df.copy()
    df["addr_id"] = [addr_id(a, b, "NJ", d) for a, b, d in zip(df[street], df[city], df[zip5])]
    recs = list({k: [k, a, b, "NJ", d] for k, a, b, d in zip(df.addr_id, df[street], df[city], df[zip5])}.values())
    g = pd.DataFrame.from_dict(geocode(recs), orient="index")
    df = df.join(g, on="addr_id")
    df["geocode_source"] = np.where(df.geocode_match == "Match", "census_geocoder", None)
    retry = df[(df.geocode_match != "Match") & df[zip5].map(retry_zip)].drop_duplicates("addr_id")
    placed = 0
    for r in retry.itertuples():
        ll = nominatim(getattr(r, street), getattr(r, city), "NJ", getattr(r, zip5))
        if ll:
            placed += 1
            hit = df.addr_id == r.addr_id
            df.loc[hit, ["lat", "lon", "geocode_source"]] = [ll[0], ll[1], "osm_nominatim"]
            df.loc[hit, "tract"] = tract_idx.lookup(*ll)
    df["county_fips"] = df.tract.str[:5]
    CONTROLS[f"{label}_geocode"] = {
        "rows": len(df), "distinct_addresses": len(recs),
        "census_matched_rows_pct": round(100 * float((df.geocode_match == "Match").mean()), 1),
        "nominatim_retried_addresses": len(retry), "nominatim_placed": placed,
        "located_rows_pct": round(100 * float(df.geocode_source.notna().mean()), 1)}
    return df


def cell_test(rows: pd.DataFrame, key):
    """Per area: (services, passes). A cell passes with >= MIN billing NPIs, >= MIN distinct billing
    SITES (geocoded points, so spelling variants of one building are one site), and no site above
    MAX_TOP_ADDRESS_SHARE of the cell."""
    st = rows.groupby(key).agg(npis=("Rndrng_NPI", "nunique"), sites=("site_key", "nunique"), svcs=("Tot_Srvcs", "sum"))
    per_site = rows.groupby([key, "site_key"]).Tot_Srvcs.sum()
    top = per_site.groupby(level=0).max()
    top2 = per_site.groupby(level=0).apply(lambda s: s.nlargest(2).sum())
    ok = ((st.npis >= C.MIN_BILLERS_FOR_VOLUME) & (st.sites >= C.MIN_BILLERS_FOR_VOLUME)
          & (top / st.svcs <= C.MAX_TOP_ADDRESS_SHARE) & (top2 / st.svcs <= C.MAX_TOP_TWO_SHARE))
    return st.svcs, ok


def merge_sites(lat, lon, meters):
    """Single-linkage clusters of points closer than `meters`; returns a cluster id per point."""
    pts = sorted(set(zip(lat.round(6), lon.round(6))))
    parent = {p: p for p in pts}

    def find(p):
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p
    for i, a in enumerate(pts):
        for b in pts[i + 1:]:
            if b[0] - a[0] > 0.001:  # sorted by latitude: ~110 m, beyond any merge distance used here
                break
            if haversine_km(a[0], a[1], b[0], b[1]) * 1000 <= meters:
                parent[find(a)] = find(b)
    ids = {p: f"{find(p)[0]:.6f},{find(p)[1]:.6f}" for p in pts}
    return [ids[p] for p in zip(lat.round(6), lon.round(6))]


def main(nppes_zip=None):
    # ---------------------------------------------------------------- 1. study area
    adj = S.county_adjacency()
    nbrs = set(adj.loc[adj.county_geoid == C.FOCUS_COUNTY, "neighbor_geoid"])
    control("study_area_is_focus_plus_all_neighbours", nbrs == set(C.COUNTIES),
            adjacency_file=sorted(nbrs), configured=sorted(C.COUNTIES))

    in_study = lambda a: a["STATEFP"] + a["COUNTYFP"] in C.COUNTIES  # noqa: E731
    tract_poly = read_polygons(download(C.TRACT_SHP), "GEOID", keep=in_study)
    cousub_poly = read_polygons(download(C.COUSUB_SHP), "GEOID", keep=in_study)
    cousub_disp = read_polygons(download(C.COUSUB_DISPLAY_SHP), "GEOID", keep=in_study)
    cousub_idx, tract_idx = PolygonIndex(cousub_poly), PolygonIndex(tract_poly)
    muni_name = {k: a["NAMELSAD"] for k, (g, a) in cousub_poly.items()}
    zctas, n_zcta, zip3 = S.study_zips()
    control("study_zctas_found", n_zcta >= 150 and zctas("07102") and not zctas("08901"), n=n_zcta, zip3_prefixes=zip3)

    # ---------------------------------------------------------------- 2. population
    acs = S.acs_tracts_and_counties()
    tr = acs[acs.level == "tract"].copy()
    co = acs[acs.level == "county"].copy()
    tr["county_fips"] = tr.geoid.str[:5]
    sums = tr.groupby("county_fips")[["pop_total", "pop_65plus"]].sum()
    cmp = co.set_index("geoid")[["pop_total", "pop_65plus"]].join(sums, rsuffix="_tract_sum")
    control("acs_tracts_sum_to_county", bool(
        (cmp.pop_total == cmp.pop_total_tract_sum).all() and (cmp.pop_65plus == cmp.pop_65plus_tract_sum).all()),
        published_county=co.set_index("geoid")[["pop_total", "pop_65plus"]].to_dict("index"))
    control("acs_has_six_counties_and_tracts", len(co) == 6 and len(tr) > 800, counties=len(co), tracts=len(tr))

    cen = S.tract_centroids()
    tr = tr.merge(cen, left_on="geoid", right_on="tract_geoid", how="left")
    no_poly = tr[(tr.pop_total > 0) & ~tr.geoid.isin(tract_poly)]
    control("populated_tracts_have_polygons", no_poly.empty, missing=no_poly.geoid.tolist())
    tr["land_sqmi"] = tr.geoid.map(lambda g: tract_poly[g][1]["ALAND"] / 2_589_988.11 if g in tract_poly else np.nan)
    tr["municipality_geoid"] = [cousub_idx.lookup(la, lo) if pd.notna(la) else None
                                for la, lo in zip(tr.centroid_lat, tr.centroid_lon)]
    tr["municipality"] = tr.municipality_geoid.map(muni_name)
    unassigned = tr[(tr.pop_total > 0) & tr.municipality_geoid.isna()]
    control("populated_tracts_assigned_a_municipality", unassigned.empty, missing=unassigned.geoid.tolist())

    # ---------------------------------------------------------------- 3. Medicare imaging use (county)
    gv = S.geo_variation()
    control("geo_variation_one_all_ages_row_per_county", len(gv) == 6 and set(gv.BENE_AGE_LVL) == {"All"},
            rows=len(gv), age_levels=sorted(set(gv.BENE_AGE_LVL)))
    gv = gv.rename(columns={"BENE_GEO_CD": "county_fips"})
    st = S.geo_variation_state()
    CONTROLS["nj_statewide_imaging_events_per_1000_by_age_2024"] = {
        **st, "ratio_65plus_to_all": round(st[">=65"] / st["All"], 4)}
    tr = tr.merge(gv[["county_fips", "IMGNG_EVNTS_PER_1000_BENES"]], on="county_fips", how="left")
    tr["est_imaging_events_65plus"] = tr.pop_65plus * tr.IMGNG_EVNTS_PER_1000_BENES / 1000

    # ---------------------------------------------------------------- 4. competitors (NPPES)
    zpath = S.nppes_zip(nppes_zip)
    orgs, codes = S.nppes_organisations(zpath)
    zero = [c for c, n in codes["org_npis_by_code_national"].items() if n == 0]
    control("every_configured_taxonomy_occurs_nationally", not zero, absent=zero,
            org_npis_by_code=codes["org_npis_by_code_national"])
    orgs["class"] = orgs.taxonomies.map(S.classify)
    orgs = place_with_fallback(orgs, "street1", "city", "zip5", zctas, tract_idx, "nppes_locations")
    control("nppes_located_rate_floor", orgs.geocode_source.notna().mean() >= 0.90,
            rate=round(float(orgs.geocode_source.notna().mean()), 3))
    study = orgs[orgs.geocode_source.notna() & orgs.county_fips.isin(C.COUNTIES)].copy()

    pecos = S.pecos_nj()
    enrolled = set(pecos.NPI)
    pecos_img = pecos[pecos.PROVIDER_TYPE_CD.isin(C.PECOS_IMAGING_TYPES)]
    control("pecos_imaging_types_all_occur_in_nj", set(pecos_img.PROVIDER_TYPE_CD) == set(C.PECOS_IMAGING_TYPES),
            occurring=sorted(set(pecos_img.PROVIDER_TYPE_CD)))
    pecos_type = pecos_img.groupby("NPI").PROVIDER_TYPE_CD.agg(
        lambda s: "|".join(sorted({C.PECOS_IMAGING_TYPES[c] for c in s})))

    pb = S.part_b_nj()
    in_pop_file = set(pb.Rndrng_NPI)
    study["medicare_enrolled_nj"] = study.NPI.isin(enrolled)
    study["pecos_imaging_type"] = study.NPI.map(pecos_type)
    study["in_cy2024_part_b_file"] = study.NPI.isin(in_pop_file)
    study["lat_r"], study["lon_r"] = study.lat.round(C.POINT_DECIMALS), study.lon.round(C.POINT_DECIMALS)
    loc = (study.groupby(["class", "lat_r", "lon_r"])
           .agg(n_npis=("NPI", "nunique"), tract_geoid=("tract", "first"),
                lat_exact=("lat", "first"), lon_exact=("lon", "first"),
                medicare_enrolled_nj=("medicare_enrolled_nj", "any"),
                pecos_imaging_type=("pecos_imaging_type", lambda s: "|".join(sorted({t for v in s.dropna() for t in v.split("|")}))),
                in_cy2024_part_b_file=("in_cy2024_part_b_file", "any"),
                location_source=("location_source", lambda s: "|".join(sorted(set(s)))))
           .reset_index().rename(columns={"lat_r": "lat", "lon_r": "lon"}))
    loc.insert(0, "location_id", [f"L{i:04d}" for i in range(1, len(loc) + 1)])
    loc["county_fips"] = loc.tract_geoid.str[:5]
    loc["municipality_geoid"] = [cousub_idx.lookup(a, b) for a, b in zip(loc.lat_exact, loc.lon_exact)]
    loc = loc.drop(columns=["lat_exact", "lon_exact"])
    loc["registered_address_only"] = loc["class"] == "mobile_or_portable"

    # ---------------------------------------------------------------- 5. Part B office imaging volume
    rb = S.rbcs_imaging()
    img = pb.merge(rb, on="HCPCS_Cd")
    control("drug_indicator_takes_only_y_or_n", set(img.HCPCS_Drug_Ind) <= {"Y", "N"}, values=sorted(set(img.HCPCS_Drug_Ind)))
    drug = img.HCPCS_Drug_Ind == "Y"
    CONTROLS["excluded_drug_and_contrast_lines"] = {
        "reason": "billed per mL or per dose, not per exam", "rows": int(drug.sum()),
        "units": float(img.loc[drug, "Tot_Srvcs"].sum()), "codes": sorted(set(img.loc[drug, "HCPCS_Cd"]))}
    img = img[~drug]
    control("every_rbcs_imaging_subcategory_occurs_in_nj", set(img.RBCS_Cat_Subcat) == set(rb.RBCS_Cat_Subcat),
            occurring=sorted(set(img.RBCS_Cat_Subcat)), defined=sorted(set(rb.RBCS_Cat_Subcat)))
    control("place_of_service_is_facility_or_nonfacility", set(img.Place_Of_Srvc) == {"F", "O"},
            values=sorted(set(img.Place_Of_Srvc)))
    control("portable_supplier_type_occurs", (img.Rndrng_Prvdr_Type == "Portable X-Ray Supplier").any())
    vol = place_with_fallback(img, "Rndrng_Prvdr_St1", "Rndrng_Prvdr_City", "Rndrng_Prvdr_Zip5", zctas, tract_idx, "part_b_billing_addresses")
    zip_rows = vol.Rndrng_Prvdr_Zip5.map(zctas)
    located = vol.loc[zip_rows & vol.geocode_source.notna(), "Tot_Srvcs"].sum() / vol.loc[zip_rows, "Tot_Srvcs"].sum()
    control("study_zcta_lines_located_floor", located >= 0.95, located_share_weighted_by_billed_count=round(float(located), 3),
            denominator="every non-drug imaging line whose billing ZIP is a study-area ZCTA or a non-ZCTA ZIP with a study ZIP3")
    in_area = vol.geocode_source.notna() & vol.county_fips.isin(C.COUNTIES)
    facility = vol.Place_Of_Srvc == "F"
    # Mobile is decided once, by class: an organisation with any fixed-site taxonomy is a fixed
    # imaging center for counting AND for volume; one with only mobile/portable codes is mobile.
    mobile_npis = set(orgs.loc[orgs["class"] == "mobile_or_portable", "NPI"])
    mobile = (vol.Rndrng_Prvdr_Type == "Portable X-Ray Supplier") | vol.Rndrng_NPI.isin(mobile_npis)
    # Counts only: no volume figure leaves the build outside the disclosure-tested county cells.
    CONTROLS["excluded_from_area_volume"] = {
        "facility_setting_lines": {"reason": "almost all are radiologists' reading fees for hospital exams, billed from their group's address",
                                   "billing_npis_in_study_area": int(vol[in_area & facility].Rndrng_NPI.nunique())},
        "mobile_or_portable_billers": {"reason": "a registered address is not where the service happens",
                                       "billing_npis_in_study_area": int(vol[in_area & mobile].Rndrng_NPI.nunique())}}
    nonfac = vol[in_area & ~facility & ~mobile].copy()
    nonfac["site_key"] = merge_sites(nonfac.lat, nonfac.lon, C.SITE_MERGE_METERS)
    CONTROLS["billing_site_merge"] = {
        "distinct_points": int(nonfac[["lat", "lon"]].round(6).drop_duplicates().shape[0]),
        "sites_after_merge": int(nonfac.site_key.nunique()), "merge_meters": C.SITE_MERGE_METERS}
    CONTROLS["nonfacility_biller_types_npi_counts"] = (
        nonfac.groupby("Rndrng_Prvdr_Type").Rndrng_NPI.nunique().sort_values(ascending=False).to_dict())
    missing_types = sorted(C.RADIOLOGY_BILLER_TYPES - set(img.Rndrng_Prvdr_Type))
    control("every_radiology_biller_type_occurs_in_nj", not missing_types, missing=missing_types)
    nonfac["modality"] = nonfac.RBCS_Subcat_Desc.map(lambda c: re.sub(r"[^a-z]+", "_", c.lower()).strip("_"))
    rad = nonfac[nonfac.Rndrng_Prvdr_Type.isin(C.RADIOLOGY_BILLER_TYPES)]
    other = nonfac[~nonfac.Rndrng_Prvdr_Type.isin(C.RADIOLOGY_BILLER_TYPES)]
    modalities = sorted(nonfac.modality.unique())
    control("six_modalities", len(modalities) == 6, modalities=modalities)
    key = "county_fips"
    vols = pd.DataFrame({key: sorted(C.COUNTIES)})
    npis_n = vols[key].map(nonfac.groupby(key).Rndrng_NPI.nunique()).fillna(0).astype(int)
    sites_n = vols[key].map(nonfac.groupby(key).site_key.nunique()).fillna(0).astype(int)
    tot, tot_ok = cell_test(nonfac, key)
    rad_v, rad_ok = cell_test(rad, key)
    _, oth_ok = cell_test(other, key)
    mods = {m: cell_test(nonfac[nonfac.modality == m], key) for m in modalities}
    # Row rule, so no hidden value is ever a difference of published ones:
    #  - the total publishes only if it passes;
    #  - the six modality cells publish all together or not at all (if any fails, the hidden union
    #    is the whole total, which passed);
    #  - radiology publishes only if both it AND everything else (total minus radiology) pass.
    # By construction a union of passing cells also passes (no site can exceed 60% of a sum of
    # cells in each of which it holds at most 60%), so the published total never needs hiding
    # because its parts pass.
    withheld = {}
    for i, f in vols[key].items():
        t_ok = bool(tot_ok.get(f, False))
        # the biller and site counts would say WHY a total was withheld, so they go with it
        vols.at[i, "nonfacility_billing_npis"] = npis_n[i] if t_ok else np.nan
        vols.at[i, "nonfacility_billing_sites"] = sites_n[i] if t_ok else np.nan
        vols.at[i, "nonfacility_imaging_svcs"] = tot.get(f) if t_ok else np.nan
        # a modality nobody billed in the county is a true zero, not a disclosure
        all_mods = t_ok and all((f not in v.index) or bool(ok[f]) for v, ok in mods.values())
        for m, (v, _) in mods.items():
            vols.at[i, f"nonfacility_svcs_{m}"] = v.get(f, 0.0) if all_mods else np.nan
        r_ok = t_ok and bool(rad_ok.get(f, False)) and bool(oth_ok.get(f, False))
        vols.at[i, "nonfacility_radiology_svcs"] = rad_v.get(f) if r_ok else np.nan
        withheld[f] = {"total": not t_ok, "modalities": not all_mods, "radiology": not r_ok}
    CONTROLS["volume_withheld"] = withheld
    vols[["nonfacility_billing_npis", "nonfacility_billing_sites"]] = vols[["nonfacility_billing_npis", "nonfacility_billing_sites"]].astype("Int64")

    # ---------------------------------------------------------------- 6. hospitals
    hosp = S.hospitals()
    hosp = place_with_fallback(hosp.assign(zip_code5=hosp.zip_code.str[:5]), "address", "citytown", "zip_code5",
                               lambda z: True, tract_idx, "hospitals")
    named = {v.upper(): k for k, v in C.COUNTIES.items()}
    listed = hosp.countyparish.str.upper().isin(named)
    placed_in = hosp.county_fips.isin(C.COUNTIES)
    agree = (listed == placed_in) & (~listed | (hosp.county_fips == hosp.countyparish.str.upper().map(named)))
    control("hospital_county_agrees_both_ways", bool(agree.all()) and listed.sum() >= 20,
            listed_in_study=int(listed.sum()), placed_in_study=int(placed_in.sum()), disagree=int((~agree).sum()))
    control("acute_hospital_type_occurs", C.ACUTE_HOSPITAL_TYPES <= set(hosp.hospital_type), types=sorted(set(hosp.hospital_type)))
    hosp = hosp[placed_in].copy()
    opps = S.opps_nj()
    imaging_apc = re.compile(r"imaging|ultrasound|nuclear medicine|mammograph|computed tomography|\bct\b|\bmri\b|x-ray|echocardiogra", re.I)
    control("imaging_apc_pattern_matches_known_imaging_wording",
            all(imaging_apc.search(s) for s in ("Level 2 Imaging without Contrast", "Level 1 Nuclear Medicine and Related Services")))
    apcs = sorted(set(opps.loc[opps.APC_Desc.str.contains(imaging_apc), "APC_Cd"]))
    CONTROLS["hospital_outpatient_imaging_volume"] = {
        "published_per_hospital": bool(apcs), "nj_apcs_in_file": int(opps.APC_Cd.nunique()), "imaging_apcs": apcs,
        "note": "Outpatient Hospitals by Provider and Service carries comprehensive APCs only"}
    hosp["is_acute_care"] = hosp.hospital_type.isin(C.ACUTE_HOSPITAL_TYPES)
    hosp["municipality_geoid"] = [cousub_idx.lookup(a, b) for a, b in zip(hosp.lat, hosp.lon)]
    hosp.insert(0, "hospital_id", [f"H{i:03d}" for i in range(1, len(hosp) + 1)])

    # ---------------------------------------------------------------- 7. nursing homes (referral sources)
    nh = S.nursing_homes()
    nh["zip5"] = nh.zip_code.str[:5]
    nh = place_with_fallback(nh, "provider_address", "citytown", "zip5", lambda z: False, tract_idx, "nursing_homes")
    nh["cms_lat"] = pd.to_numeric(nh.latitude, errors="coerce")
    nh["cms_lon"] = pd.to_numeric(nh.longitude, errors="coerce")
    both = nh[(nh.geocode_match == "Match") & nh.cms_lat.notna()]
    d = [haversine_km(a, b, c, e) for a, b, c, e in zip(both.lat, both.lon, both.cms_lat, both.cms_lon)]
    control("geocoder_agrees_with_cms_nursing_home_coordinates", float(np.median(d)) < 0.5,
            compared=len(d), median_km=round(float(np.median(d)), 3), over_1km=int(sum(x > 1 for x in d)))
    fb = nh.geocode_source.isna() & nh.cms_lat.notna()
    nh.loc[fb, ["lat", "lon", "geocode_source"]] = list(zip(nh.loc[fb, "cms_lat"], nh.loc[fb, "cms_lon"], ["cms_coordinates"] * fb.sum()))
    nh.loc[fb, "tract"] = [tract_idx.lookup(a, b) for a, b in zip(nh.loc[fb, "lat"], nh.loc[fb, "lon"])]
    nh["county_fips"] = nh.tract.str[:5]
    listed = nh.countyparish.str.upper().isin(named)
    placed_in = nh.county_fips.isin(C.COUNTIES)
    agree = (listed == placed_in) & (~listed | (nh.county_fips == nh.countyparish.str.upper().map(named)))
    control("nursing_home_county_agrees_both_ways", bool(agree.all()) and listed.sum() >= 100,
            listed_in_study=int(listed.sum()), placed_in_study=int(placed_in.sum()), disagree=int((~agree).sum()),
            disagreements=nh.loc[~agree, ["countyparish", "county_fips", "geocode_source"]].to_dict("records"))
    nh = nh[placed_in].copy()
    nh["certified_beds"] = pd.to_numeric(nh.number_of_certified_beds, errors="coerce")
    nh["avg_residents_per_day"] = pd.to_numeric(nh.average_number_of_residents_per_day, errors="coerce")
    nh["municipality_geoid"] = [cousub_idx.lookup(a, b) for a, b in zip(nh.lat, nh.lon)]
    nh.insert(0, "nursing_home_id", [f"N{i:03d}" for i in range(1, len(nh) + 1)])

    # ---------------------------------------------------------------- 8. drive times
    sites = pd.DataFrame(C.SITES)
    src = list(zip(sites.lat, sites.lon))
    tr_d = tr[tr.centroid_lat.notna()]
    fixed = loc[~loc.registered_address_only]
    dests = (list(zip(tr_d.centroid_lat, tr_d.centroid_lon)) + list(zip(fixed.lat, fixed.lon))
             + list(zip(hosp.lat, hosp.lon)) + list(zip(nh.lat, nh.lon)))
    mins, kms, snap = osrm_table(src, dests)
    n1, n2, n3 = len(tr_d), len(tr_d) + len(fixed), len(tr_d) + len(fixed) + len(hosp)
    dcols = [f"drive_min_{s}" for s in sites.site_id]
    for i, s in enumerate(sites.site_id):
        tr.loc[tr_d.index, f"drive_min_{s}"] = mins[i][:n1]
        loc.loc[fixed.index, f"drive_min_{s}"] = mins[i][n1:n2]
        hosp[f"drive_min_{s}"] = mins[i][n2:n3]
        nh[f"drive_min_{s}"] = mins[i][n3:]
    unroutable = sum(m is None for row in mins for m in row)
    control("osrm_routed_every_destination", unroutable == 0, unroutable=unroutable, destinations=len(dests))
    snaps = np.array(snap, dtype=float)
    control("osrm_snapped_within_1km", float(np.nanmax(snaps)) < 1000, max_snap_m=round(float(np.nanmax(snaps)), 1),
            over_250m=int((snaps > 250).sum()), median_m=round(float(np.nanmedian(snaps)), 1))
    own = {s: tract_idx.lookup(la, lo) for s, la, lo in zip(sites.site_id, sites.lat, sites.lon)}
    own_ok = {s: bool(tr.loc[tr.geoid == g, f"drive_min_{s}"].iloc[0] == tr.loc[tr.geoid == g, dcols].min(axis=1).iloc[0]) for s, g in own.items()}
    control("each_site_is_nearest_to_its_own_tract", all(own_ok.values()), detail=own_ok, own_tracts=own)
    tr["drive_min_nearest_site"] = tr[dcols].min(axis=1)
    tr["nearest_site"] = tr[dcols].idxmin(axis=1).str[-1].where(tr.drive_min_nearest_site.notna())

    # ---------------------------------------------------------------- 9. site coverage
    moe = lambda s: float(np.sqrt((s ** 2).sum()))  # noqa: E731
    rows = []
    for s in sites.itertuples():
        col = f"drive_min_{s.site_id}"
        for band in C.DRIVE_BANDS_MIN:
            tin = tr[tr[col] <= band]
            r = {"site_id": s.site_id, "band_min": band, "tracts": len(tin),
                 "pop_total": tin.pop_total.sum(), "pop_65plus": tin.pop_65plus.sum(),
                 "pop_65plus_moe": round(moe(tin.pop_65plus_moe)),
                 "pct_study_area_65plus": round(100 * tin.pop_65plus.sum() / tr.pop_65plus.sum(), 1),
                 "est_imaging_events_65plus": round(tin.est_imaging_events_65plus.sum()),
                 "nursing_homes": int((nh[col] <= band).sum()),
                 "nursing_home_beds": nh.loc[nh[col] <= band, "certified_beds"].sum(),
                 "acute_care_hospitals": int(((hosp[col] <= band) & hosp.is_acute_care).sum()),
                 "imaging_center_locations": int(((loc[col] <= band) & (loc["class"] == "imaging_center")).sum()),
                 "radiology_group_offices": int(((loc[col] <= band) & (loc["class"] == "radiology_group")).sum())}
            r["imaging_center_locations_per_100k_65plus"] = (
                round(1e5 * r["imaging_center_locations"] / r["pop_65plus"], 1) if r["pop_65plus"] else None)
            rows.append(r)
    coverage = pd.DataFrame(rows)

    # ---------------------------------------------------------------- 10. area tables
    for df in (loc, hosp, nh):
        df["municipality"] = df.municipality_geoid.map(muni_name)

    def area(key, keys, label_map):
        g = pd.DataFrame({key: keys})
        a = tr.groupby(key).agg(tracts=("geoid", "count"), pop_total=("pop_total", "sum"),
                                pop_65plus=("pop_65plus", "sum"), land_sqmi=("land_sqmi", "sum"),
                                est_imaging_events_65plus=("est_imaging_events_65plus", "sum"))
        a["pop_65plus_moe"] = tr.groupby(key).pop_65plus_moe.apply(moe).round()
        g = g.merge(a.reset_index(), on=key, how="left")
        fill = {}
        fill["imaging_center_locations"] = loc[loc["class"] == "imaging_center"].groupby(key).size()
        fill["radiology_group_offices"] = loc[loc["class"] == "radiology_group"].groupby(key).size()
        fill["acute_care_hospitals"] = hosp[hosp.is_acute_care].groupby(key).size()
        fill["other_hospitals"] = hosp[~hosp.is_acute_care].groupby(key).size()
        fill["nursing_homes"] = nh.groupby(key).size()
        fill["nursing_home_beds"] = nh.groupby(key).certified_beds.sum()
        for c, s in fill.items():
            g[c] = g[key].map(s).fillna(0).astype(int)
        for c in ("tracts", "pop_total", "pop_65plus"):
            g[c] = g[c].fillna(0)
        g.insert(1, label_map[0], g[key].map(label_map[1]))
        has = g.pop_65plus > 0
        g["pct_65plus"] = (100 * g.pop_65plus / g.pop_total).where(has).round(1)
        g["nursing_home_beds_per_1000_65plus"] = (1000 * g.nursing_home_beds / g.pop_65plus).where(has).round(1)
        g["nursing_homes_per_sqmi"] = (g.nursing_homes / g.land_sqmi).round(3)
        g["imaging_center_locations_per_100k_65plus"] = (1e5 * g.imaging_center_locations / g.pop_65plus).where(has).round(1)
        return g

    counties = area("county_fips", sorted(C.COUNTIES), ("county_name", C.COUNTIES))
    gvo = gv.rename(columns={
        "BENES_TOTAL_CNT": "medicare_benes_2024", "BENES_OM_CNT": "original_medicare_benes_2024",
        "BENES_MA_CNT": "medicare_advantage_benes_2024", "MA_PRTCPTN_RATE": "ma_participation_rate",
        "BENES_IMGNG_PCT": "om_benes_using_imaging_pct", "IMGNG_EVNTS_PER_1000_BENES": "om_imaging_events_per_1000_benes",
        "IMGNG_MDCR_STDZD_PYMT_PC": "om_imaging_std_payment_per_capita"})
    gvo["neither_om_nor_ma_benes_2024"] = gvo.medicare_benes_2024 - gvo.original_medicare_benes_2024 - gvo.medicare_advantage_benes_2024
    gvo["original_medicare_share_of_all"] = (gvo.original_medicare_benes_2024 / gvo.medicare_benes_2024).round(3)
    counties = counties.merge(gvo[["county_fips", "medicare_benes_2024", "original_medicare_benes_2024",
                                   "medicare_advantage_benes_2024", "neither_om_nor_ma_benes_2024",
                                   "original_medicare_share_of_all", "ma_participation_rate",
                                   "om_benes_using_imaging_pct", "om_imaging_events_per_1000_benes",
                                   "om_imaging_std_payment_per_capita"]], on="county_fips", how="left")
    counties = counties.merge(vols, on="county_fips", how="left")
    CONTROLS["county_inputs"] = {"geo_variation": gvo.set_index("county_fips")[[
        "om_imaging_events_per_1000_benes", "ma_participation_rate"]].to_dict("index")}
    munis = area("municipality_geoid", sorted(cousub_poly), ("municipality", muni_name))
    munis.insert(2, "county_fips", munis.municipality_geoid.str[:5])
    munis["land_sqmi"] = munis.municipality_geoid.map(lambda k: cousub_poly[k][1]["ALAND"] / 2_589_988.11)
    munis["nursing_homes_per_sqmi"] = (munis.nursing_homes / munis.land_sqmi).round(3)
    control("every_point_lands_in_a_municipality_row",
            all(set(df.municipality_geoid.dropna()) <= set(munis.municipality_geoid) for df in (loc, hosp, nh))
            and all(df.municipality_geoid.notna().all() for df in (loc, hosp, nh)),
            municipalities=len(munis))
    control("area_counts_reconcile_with_points",
            int(munis.nursing_homes.sum()) == len(nh) == int(counties.nursing_homes.sum())
            and int(munis.imaging_center_locations.sum()) == int((loc["class"] == "imaging_center").sum()) == int(counties.imaging_center_locations.sum()),
            nursing_homes=len(nh))

    # ---------------------------------------------------------------- 11. serialise, check, then write
    rp = C.POINT_DECIMALS
    tracts_out = tr[["geoid", "county_fips", "municipality_geoid", "municipality", "pop_total", "pop_total_moe",
                     "pop_65plus", "pop_65plus_moe", "median_hh_income", "median_hh_income_moe", "land_sqmi",
                     "centroid_lat", "centroid_lon", "IMGNG_EVNTS_PER_1000_BENES", "est_imaging_events_65plus",
                     *dcols, "drive_min_nearest_site", "nearest_site"]].rename(columns={
                         "geoid": "tract_geoid", "IMGNG_EVNTS_PER_1000_BENES": "county_om_imaging_events_per_1000"})
    tracts_out.insert(2, "county_name", tracts_out.county_fips.map(C.COUNTIES))
    r1 = lambda df, cols: df.assign(**{c: df[c].round(1) for c in cols if c in df})  # noqa: E731
    # Point drive times are whole minutes: three times to 0.1 minute from published sites would
    # place a point more precisely than its rounded coordinates.
    r0 = lambda df, cols: df.assign(**{c: df[c].round(0) for c in cols if c in df})  # noqa: E731
    tables = {
        "tracts.csv": r1(tracts_out, ["land_sqmi", "est_imaging_events_65plus", "pop_65plus_moe", *dcols, "drive_min_nearest_site"]),
        "counties.csv": counties,
        "municipalities.csv": munis,
        "competitor_locations.csv": r0(loc.assign(county_name=loc.county_fips.map(C.COUNTIES))[[
            "location_id", "class", "registered_address_only", "n_npis", "lat", "lon", "tract_geoid", "county_fips",
            "county_name", "municipality_geoid", "municipality", "medicare_enrolled_nj", "pecos_imaging_type",
            "in_cy2024_part_b_file", "location_source", *dcols]], dcols),
        "hospitals.csv": r0(hosp.assign(county_name=hosp.county_fips.map(C.COUNTIES), lat=hosp.lat.round(rp), lon=hosp.lon.round(rp),
                                        tract_geoid=hosp.tract)[[
            "hospital_id", "hospital_type", "is_acute_care", "emergency_services", "lat", "lon", "geocode_source",
            "tract_geoid", "county_fips", "county_name", "municipality_geoid", "municipality", *dcols]], dcols),
        "nursing_homes.csv": r0(nh.assign(county_name=nh.county_fips.map(C.COUNTIES), lat=nh.lat.round(rp), lon=nh.lon.round(rp),
                                          tract_geoid=nh.tract)[[
            "nursing_home_id", "certified_beds", "lat", "lon", "geocode_source", "tract_geoid",
            "county_fips", "county_name", "municipality_geoid", "municipality", *dcols]], dcols),
        "sites.csv": sites,
        "site_coverage.csv": coverage,
    }
    texts = {n: df.to_csv(index=False, lineterminator="\n") for n, df in tables.items()}
    texts["geo/study_tracts.geojson"] = geojson_text(tract_poly, lambda k, a: {"tract_geoid": k, "county_fips": k[:5]})
    texts["geo/study_municipalities.geojson"] = geojson_text(
        cousub_disp, lambda k, a: {"municipality_geoid": k, "municipality": a.get("NAMELSAD") or a.get("NAME")})

    CONTROLS["row_counts"] = {n: len(df) for n, df in tables.items()}
    CONTROLS["sources"] = {
        "nppes_file": str(zpath).replace("\\", "/").rsplit("/", 1)[-1],
        "acs": "2020-2024 5-year table-based summary files",
        "pecos": "Medicare FFS Public Provider Enrollment, quarter from 2026-07-01 (filtered STATE_CD=NJ)",
        "part_b": "Medicare Physician & Other Practitioners by Provider and Service, CY2024",
        "geo_variation": "Medicare Geographic Variation by National, State & County, 2024",
        "rbcs": C.RBCS_CSV.rsplit("/", 1)[-1],
        "care_compare_modified": {k: S.provider_data_modified(v) for k, v in C.CARE_COMPARE.items()},
        "cms_uuids": C.CMS}
    CONTROLS["manifest_sha256"] = {n: hashlib.sha256(t.encode("utf-8")).hexdigest() for n, t in texts.items()}

    # Identity checks over EVERYTHING that will be written, controls.json included.
    names = set(orgs.org_name) | set(S.hospitals().facility_name)         | set(S.nursing_homes().provider_name) | set(S.nursing_homes().legal_business_name)         | set(pb.loc[pb.Rndrng_Prvdr_Ent_Cd == "O", "Rndrng_Prvdr_Last_Org_Name"])
    names = {n.upper().strip() for n in names if isinstance(n, str) and len(n.strip()) >= 8}
    # The one exception: a public body billing under its own place name (a township's ambulance
    # service bills as "... TOWNSHIP"). Only an exact Census municipality name is exempt; the
    # exemptions are recorded by GEOID.
    by_name = {v.upper(): k for k, v in muni_name.items()}
    exempt = sorted(by_name[n] for n in names & by_name.keys())
    names -= by_name.keys()
    npis = set(orgs.NPI) | set(pb.Rndrng_NPI) | set(pecos.NPI)
    CONTROLS["no_organisation_name_in_any_output"] = {"passed": True, "names_checked": len(names),
                                                      "exempt_municipality_geoids": exempt}
    CONTROLS["no_npi_in_any_output"] = {"passed": True, "npis_checked": len(npis)}
    controls_text = json.dumps(CONTROLS, indent=1, default=str)
    blob = ("\n".join(texts.values()) + "\n" + controls_text).upper()
    hits = sorted(n for n in names if n in blob)
    control("no_organisation_name_in_any_output", not hits and len(names) > 500, names_checked=len(names),
            hits=hits[:10], exempt_municipality_geoids=exempt)
    tokens = set(re.findall(r"(?<!\d)\d{10}(?!\d)", blob))
    control("no_npi_in_any_output", not (tokens & npis) and len(npis) > 50_000, npis_checked=len(npis),
            ten_digit_tokens_in_output=len(tokens), hits=len(tokens & npis))
    muni_vol = [c for c in munis.columns if "svcs" in c or "volume" in c or "billing" in c]
    control("no_volume_below_county_grain", not muni_vol and not [c for c in tables["competitor_locations.csv"].columns if "svcs" in c],
            municipal_volume_columns=muni_vol)
    texts["controls.json"] = json.dumps(CONTROLS, indent=1, default=str)

    # Atomic replace: write everything to a staging directory, then swap it in whole.
    import shutil
    out, stage, old = C.OUT, C.OUT.with_name("output.staging"), C.OUT.with_name("output.previous")
    for d in (stage, old):
        if d.exists():
            shutil.rmtree(d)
    (stage / "geo").mkdir(parents=True)
    for n, t in texts.items():
        (stage / n).write_text(t, encoding="utf-8", newline="")
    if out.exists():
        out.rename(old)
    stage.rename(out)
    if old.exists():
        shutil.rmtree(old)
    print(json.dumps(CONTROLS["row_counts"], indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--nppes-zip", default=None, help="path to an already-downloaded NPPES monthly V2 zip")
    main(ap.parse_args().nppes_zip)
