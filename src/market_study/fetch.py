"""Cached downloads. Every network read lands in data/raw so a re-run is offline and identical."""
import hashlib
import json
import time
from pathlib import Path

import requests

from .config import RAW

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "imaging-market-study (public-data research)"


def _get(url, params=None, tries=4, **kw):
    for i in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=120, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if i == tries - 1:
                raise
            time.sleep(2 ** i)


def download(url: str, name: str | None = None) -> Path:
    """Download a file once into data/raw/files/ and return its path."""
    dest = RAW / "files" / (name or url.rsplit("/", 1)[-1])
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True) as r, open(tmp, "wb") as fh:
        for block in r.iter_content(1 << 20):
            fh.write(block)
    tmp.replace(dest)
    return dest


def _cache_path(kind: str, key: str) -> Path:
    h = hashlib.sha256(key.encode()).hexdigest()[:20]
    return RAW / "api" / kind / f"{h}.json"


def cms_api(uuid: str, filters: dict[str, str], page: int = 5000) -> list[dict]:
    """All rows of a data.cms.gov dataset matching equality filters.

    The API silently ignores a filter on a misspelled column and returns the whole
    table, so the result is checked: the filtered count must be below the table's
    total, above zero, and every returned row must carry the filtered value.
    """
    key = json.dumps([uuid, sorted(filters.items())])
    cache = _cache_path("cms", key)
    if cache.exists():
        return json.loads(cache.read_text())
    base = f"https://data.cms.gov/data-api/v1/dataset/{uuid}/data"
    params = {f"filter[{k}]": v for k, v in filters.items()}
    stats = _get(base + "/stats", params=params).json()
    found, total = stats["found_rows"], stats["total_rows"]
    if not 0 < found < total:
        raise RuntimeError(f"filter {filters} on {uuid} matched {found} of {total}: refusing an unfiltered or empty pull")
    rows = []
    for offset in range(0, found, page):
        rows.extend(_get(base, params={**params, "size": page, "offset": offset}).json())
    if len(rows) != found:
        raise RuntimeError(f"{uuid}: expected {found} rows, received {len(rows)}")
    for k, v in filters.items():
        bad = sum(1 for r in rows if str(r.get(k)) != v)
        if bad:
            raise RuntimeError(f"{uuid}: {bad} rows do not carry {k}={v}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows


def provider_data(dataset_id: str, state: str) -> list[dict]:
    """All Care Compare (provider-data) rows for one state, with the same checks."""
    cache = _cache_path("provider_data", f"{dataset_id}|{state}")
    if cache.exists():
        return json.loads(cache.read_text())
    base = f"https://data.cms.gov/provider-data/api/1/datastore/query/{dataset_id}/0"
    rows, offset = [], 0
    while True:
        params = {"conditions[0][property]": "state", "conditions[0][value]": state,
                  "conditions[0][operator]": "=", "limit": 500, "offset": offset, "count": "true"}
        d = _get(base, params=params).json()
        rows.extend(d["results"])
        offset += 500
        if offset >= int(d["count"]):
            break
    if not rows or any(r["state"] != state for r in rows):
        raise RuntimeError(f"{dataset_id}: state filter did not hold")
    if len(rows) != int(d["count"]):
        raise RuntimeError(f"{dataset_id}: expected {d['count']} rows, received {len(rows)}")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(rows))
    return rows
