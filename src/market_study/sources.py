"""Readers for each public source. Each returns plain pandas frames; nothing is written to output here."""
import io
import json
import re
import zipfile

import pandas as pd

from . import config as C
from .fetch import _get, cms_api, download, provider_data

NA_JAM = {"", "-", "N", "(X)", "*****", "-666666666", "-999999999", "-888888888", "-555555555", "-333333333", "-222222222"}


# --------------------------------------------------------------------------- Census
def county_adjacency():
    path = download(C.COUNTY_ADJACENCY)
    adj = pd.read_csv(path, sep="|", dtype=str, encoding="latin-1")
    adj.columns = ["county_name", "county_geoid", "neighbor_name", "neighbor_geoid", *adj.columns[4:]][: len(adj.columns)]
    return adj


def acs_table(table: str, geoids_prefixes: tuple[str, ...]) -> pd.DataFrame:
    """Rows of one ACS 5-year table-based summary file whose GEO_ID starts with a prefix."""
    path = download(C.ACS_SF.format(table=table))
    keep = []
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("|")
        for line in fh:
            if line.startswith(geoids_prefixes):
                keep.append(line.rstrip("\n").split("|"))
    df = pd.DataFrame(keep, columns=header)
    for c in header[1:]:
        df[c] = pd.to_numeric(df[c].where(~df[c].isin(NA_JAM)), errors="coerce")
        df.loc[df[c] < 0, c] = pd.NA
    return df


def acs_tracts_and_counties():
    tract_prefixes = tuple(f"1400000US{c}" for c in C.COUNTIES)
    county_prefixes = tuple(f"0500000US{c}" for c in C.COUNTIES)
    prefixes = tract_prefixes + county_prefixes
    age = acs_table("b01001", prefixes)
    tot = acs_table("b01003", prefixes)
    inc = acs_table("b19013", prefixes)
    e65 = [f"B01001_E{n:03d}" for n in (20, 21, 22, 23, 24, 25, 44, 45, 46, 47, 48, 49)]
    m65 = [c.replace("_E", "_M") for c in e65]
    age["pop_65plus"] = age[e65].sum(axis=1, min_count=len(e65))
    age["pop_65plus_moe"] = (age[m65] ** 2).sum(axis=1) ** 0.5
    df = (tot[["GEO_ID", "B01003_E001", "B01003_M001"]]
          .merge(age[["GEO_ID", "B01001_E001", "pop_65plus", "pop_65plus_moe"]], on="GEO_ID", how="outer")
          .merge(inc[["GEO_ID", "B19013_E001", "B19013_M001"]], on="GEO_ID", how="left"))
    df = df.rename(columns={"B01003_E001": "pop_total", "B01003_M001": "pop_total_moe",
                            "B19013_E001": "median_hh_income", "B19013_M001": "median_hh_income_moe"})
    df["geoid"] = df.GEO_ID.str.split("US").str[1]
    df["level"] = df.GEO_ID.str[:3].map({"140": "tract", "050": "county"})
    return df


def tract_centroids():
    path = download(C.CENPOP_TRACTS)
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df["tract_geoid"] = df.STATEFP + df.COUNTYFP + df.TRACTCE
    df["centroid_lat"] = df.LATITUDE.astype(float)
    df["centroid_lon"] = df.LONGITUDE.astype(float)
    df["cenpop2020"] = df.POPULATION.astype(int)
    return df[["tract_geoid", "centroid_lat", "centroid_lon", "cenpop2020"]]


# --------------------------------------------------------------------------- CMS
def geo_variation(year="2024"):
    rows = []
    for fips in C.COUNTIES:
        rows += cms_api(C.CMS["geo_variation"], {"BENE_GEO_CD": fips, "YEAR": year})
    keep = ["BENE_GEO_CD", "BENE_GEO_DESC", "BENE_AGE_LVL", "YEAR", "BENES_TOTAL_CNT", "BENES_OM_CNT", "BENES_MA_CNT",
            "MA_PRTCPTN_RATE", "BENE_AVG_AGE", "BENES_IMGNG_CNT", "BENES_IMGNG_PCT", "IMGNG_EVNTS_PER_1000_BENES",
            "IMGNG_MDCR_STDZD_PYMT_PC"]
    df = pd.DataFrame(rows)[keep]
    for c in keep[4:]:
        df[c] = pd.to_numeric(df[c].replace({"*": None, "": None}), errors="coerce")
    return df


def pecos_nj():
    df = pd.DataFrame(cms_api(C.CMS["pecos_enrollment"], {"STATE_CD": C.STATE_ABBR}))
    return df[["NPI", "PROVIDER_TYPE_CD", "PROVIDER_TYPE_DESC", "ENRLMT_ID"]]


def rbcs_imaging():
    path = download(C.RBCS_CSV)
    df = pd.read_csv(path, dtype=str, encoding="latin-1", keep_default_na=False)
    df = df[(df.RBCS_Cat == "I") & (df.RBCS_Latest_Assignment == "1")]
    return df[["HCPCS_Cd", "RBCS_Cat_Subcat", "RBCS_Subcat_Desc"]].drop_duplicates("HCPCS_Cd")


def part_b_nj():
    df = pd.DataFrame(cms_api(C.CMS["pop_provider_service"], {"Rndrng_Prvdr_State_Abrvtn": C.STATE_ABBR}))
    for c in ("Tot_Benes", "Tot_Srvcs", "Tot_Bene_Day_Srvcs"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def opps_nj():
    df = pd.DataFrame(cms_api(C.CMS["opps_provider_service"], {"Rndrng_Prvdr_State_Abrvtn": C.STATE_ABBR}))
    for c in ("Bene_Cnt", "CAPC_Srvcs"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def nursing_homes():
    return pd.DataFrame(provider_data(C.CARE_COMPARE["nursing_homes"], C.STATE_ABBR))


def hospitals():
    return pd.DataFrame(provider_data(C.CARE_COMPARE["hospitals"], C.STATE_ABBR))


# --------------------------------------------------------------------------- NPPES
def nppes_zip(path_hint=None):
    """The current NPPES monthly V2 file: a given path, or download the one the index links."""
    if path_hint:
        return path_hint
    html = _get(C.NPPES_INDEX).text
    name = re.search(r"NPPES_Data_Dissemination_[A-Za-z]+_\d{4}_V2\.zip", html).group(0)
    return download("https://download.cms.gov/nppes/" + name, name)


def nppes_organisations(zip_path):
    """NJ practice locations (primary and secondary) of organisation NPIs with a study taxonomy."""
    stem = re.sub(r"\W", "_", str(zip_path).replace("\\", "/").rsplit("/", 1)[-1])
    cache = C.RAW / "nppes" / (stem + ".study2.csv.gz")
    counts_file = C.RAW / "nppes" / (stem + ".study2.codes.json")
    if cache.exists() and counts_file.exists():
        df = pd.read_csv(cache, dtype=str, keep_default_na=False)
        return df, json.loads(counts_file.read_text())
    df, counts = _nppes_organisations(zip_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    counts_file.write_text(json.dumps(counts))
    return df, counts


def _nppes_organisations(zip_path):
    study = {**C.IMAGING_CENTER_TAXONOMY, **C.RADIOLOGY_GROUP_TAXONOMY, **C.MOBILE_OR_PORTABLE_TAXONOMY}
    code_counts = {c: 0 for c in study}
    tax = [f"Healthcare Provider Taxonomy Code_{i}" for i in range(1, 16)]
    cols = ["NPI", "Entity Type Code", "Provider Organization Name (Legal Business Name)",
            "Provider First Line Business Practice Location Address",
            "Provider Second Line Business Practice Location Address",
            "Provider Business Practice Location Address City Name",
            "Provider Business Practice Location Address State Name",
            "Provider Business Practice Location Address Postal Code",
            "Provider Enumeration Date", "Last Update Date", "Is Organization Subpart"] + tax
    zf = zipfile.ZipFile(zip_path)
    main = next(n for n in zf.namelist() if n.startswith("npidata_pfile") and not n.endswith("fileheader.csv"))
    pl = next(n for n in zf.namelist() if n.startswith("pl_pfile") and not n.endswith("fileheader.csv"))
    keep, all_npis = [], {}
    with zf.open(main) as fh:
        for ch in pd.read_csv(fh, usecols=cols, dtype=str, chunksize=500_000, keep_default_na=False):
            ch = ch[ch["Entity Type Code"] == "2"]
            hit = ch[tax].isin(study.keys()).any(axis=1)
            ch = ch[hit].copy()
            ch["taxonomies"] = ch[tax].apply(lambda r: "|".join(v for v in r if v), axis=1)
            for npi, t, name in zip(ch.NPI, ch.taxonomies, ch["Provider Organization Name (Legal Business Name)"]):
                all_npis[npi] = (t, name)
                for c in set(t.split("|")) & study.keys():
                    code_counts[c] += 1
            nj = ch[ch["Provider Business Practice Location Address State Name"] == C.STATE_ABBR]
            keep.append(nj.drop(columns=tax))
    prim = pd.concat(keep).rename(columns={
        "Provider Organization Name (Legal Business Name)": "org_name",
        "Provider First Line Business Practice Location Address": "street1",
        "Provider Second Line Business Practice Location Address": "street2",
        "Provider Business Practice Location Address City Name": "city",
        "Provider Business Practice Location Address State Name": "state",
        "Provider Business Practice Location Address Postal Code": "zip",
        "Provider Enumeration Date": "enumeration_date", "Last Update Date": "last_update",
        "Is Organization Subpart": "is_subpart"})
    prim["location_source"] = "primary"
    sec = []
    with zf.open(pl) as fh:
        for ch in pd.read_csv(fh, dtype=str, chunksize=500_000, keep_default_na=False):
            ch.columns = ["NPI", "street1", "street2", "city", "state", "zip", "country", "phone", "ext", "fax"]
            ch = ch[(ch.state == C.STATE_ABBR) & ch.NPI.isin(all_npis)]
            sec.append(ch[["NPI", "street1", "street2", "city", "state", "zip"]])
    sec = pd.concat(sec)
    sec["taxonomies"] = sec.NPI.map(lambda n: all_npis[n][0])
    sec["org_name"] = sec.NPI.map(lambda n: all_npis[n][1])
    sec["location_source"] = "secondary"
    df = pd.concat([prim, sec], ignore_index=True)
    df["zip5"] = df.zip.str[:5]
    return df, {"national_study_taxonomy_org_npis": len(all_npis), "org_npis_by_code_national": code_counts}


def classify(taxonomies: str) -> str:
    """A fixed-site imaging taxonomy wins; then mobile/portable; anything else here is a group."""
    codes = taxonomies.split("|")
    if any(c in C.IMAGING_CENTER_TAXONOMY for c in codes):
        return "imaging_center"
    if any(c in C.MOBILE_OR_PORTABLE_TAXONOMY for c in codes):
        return "mobile_or_portable"
    return "radiology_group"


def is_mobile(taxonomies: str) -> bool:
    return any(c in C.MOBILE_OR_PORTABLE_TAXONOMY for c in taxonomies.split("|"))


def study_zips():
    """ZIPs treated as study-area ZIPs for geocoding retries and the located-share floor.

    ZCTAs with any land in the six counties (Census 2020 relationship file), plus every ZIP that
    has no ZCTA at all (PO-box and single-site ZIPs, e.g. a hospital campus) but shares a
    three-digit prefix with one of them. Returned as a predicate on a ZIP5 string.
    """
    path = download(C.ZCTA_COUNTY_REL)
    rel = pd.read_csv(path, sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel[rel.GEOID_ZCTA5_20.notna()]
    every = set(rel.GEOID_ZCTA5_20)
    study = set(rel.loc[rel.GEOID_COUNTY_20.isin(C.COUNTIES) & (pd.to_numeric(rel.AREALAND_PART) > 0), "GEOID_ZCTA5_20"])
    prefixes = {z[:3] for z in study}
    pred = lambda z: isinstance(z, str) and (z in study or (z[:3] in prefixes and z not in every))  # noqa: E731
    return pred, len(study), sorted(prefixes)


def geo_variation_state(year="2024"):
    rows = cms_api(C.CMS["geo_variation"], {"BENE_GEO_DESC": C.GV_STATE_DESC, "YEAR": year})
    return {r["BENE_AGE_LVL"]: float(r["IMGNG_EVNTS_PER_1000_BENES"]) for r in rows}


def provider_data_modified(dataset_id):
    meta = _get(f"https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items/{dataset_id}").json()
    return meta.get("modified")
