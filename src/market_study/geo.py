"""Geocoding (Census batch geocoder), polygon lookup, distances, GeoJSON export."""
import csv
import hashlib
import io
import json
import math

import shapefile
from shapely.geometry import Point, mapping, shape
from shapely.strtree import STRtree

from .config import GEOCODER_BATCH, RAW
from .fetch import SESSION


def read_polygons(zip_path, key_field, keep=None):
    """{key: (shapely geometry, attributes)} from a zipped shapefile."""
    out = {}
    with shapefile.Reader(str(zip_path)) as r:
        fields = [f[0] for f in r.fields[1:]]
        for sr in r.iterShapeRecords():
            attrs = dict(zip(fields, sr.record))
            if keep and not keep(attrs):
                continue
            out[attrs[key_field]] = (shape(sr.shape.__geo_interface__), attrs)
    return out


class PolygonIndex:
    def __init__(self, polygons):
        self.keys = list(polygons)
        self.geoms = [polygons[k][0] for k in self.keys]
        self.tree = STRtree(self.geoms)

    def lookup(self, lat, lon):
        p = Point(lon, lat)
        for i in self.tree.query(p):
            if self.geoms[i].covers(p):
                return self.keys[i]
        return None


def geojson_text(polygons, props):
    feats = [{"type": "Feature", "geometry": mapping(geom), "properties": props(k, a)} for k, (geom, a) in polygons.items()]
    return json.dumps({"type": "FeatureCollection", "features": feats})


def write_geojson(polygons, path, props):
    feats = [{"type": "Feature", "geometry": mapping(g), "properties": props(k, a)} for k, (g, a) in polygons.items()]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _retry(call, tries=5):
    import time
    import requests
    for i in range(tries):
        try:
            r = call()
            r.raise_for_status()
            return r
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if i == tries - 1:
                raise
            time.sleep(3 * 2 ** i)


def nominatim(street, city, state, zip5):
    """Fallback single-address geocode via OpenStreetMap Nominatim (1 request/second policy)."""
    import time
    q = {"street": street, "city": city, "state": state, "postalcode": zip5, "country": "us", "format": "json", "limit": 1}
    key = json.dumps(q, sort_keys=True)
    cache = RAW / "nominatim" / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")
    if cache.exists():
        res = json.loads(cache.read_text())
    else:
        r = _retry(lambda: SESSION.get("https://nominatim.openstreetmap.org/search", params=q, timeout=60))
        res = r.json()
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(res))
        time.sleep(1.1)
    if not res:
        return None
    return float(res[0]["lat"]), float(res[0]["lon"])


def geocode(records, chunk=500):
    """records: list of (id, street, city, state, zip). Returns {id: {...}} for every id.

    Uses the Census Geocoder's batch endpoint (benchmark Public_AR_Current) and keeps
    its match flag, match type, coordinates and 2020 tract. Results are cached per chunk.
    """
    out = {}
    for i in range(0, len(records), chunk):
        part = records[i:i + chunk]
        buf = io.StringIO()
        csv.writer(buf).writerows(part)
        body = buf.getvalue()
        cache = RAW / "geocode" / (hashlib.sha256(body.encode()).hexdigest()[:20] + ".csv")
        if not cache.exists():
            r = _retry(lambda: SESSION.post(GEOCODER_BATCH, files={"addressFile": ("a.csv", body)},
                                            data={"benchmark": "Public_AR_Current", "vintage": "Current_Current"},
                                            timeout=600))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(r.text)
        for row in csv.reader(io.StringIO(cache.read_text())):
            if not row:
                continue
            rid, match = row[0], (row[2] if len(row) > 2 else "")
            rec = {"geocode_match": match, "geocode_type": "", "lat": None, "lon": None, "tract": None}
            if match == "Match" and len(row) >= 12:
                lon, lat = row[5].split(",")
                rec.update(geocode_type=row[3], lat=float(lat), lon=float(lon),
                           tract=f"{row[8]}{row[9]}{row[10]}")
            out[rid] = rec
    missing = [r[0] for r in records if r[0] not in out]
    if missing:
        raise RuntimeError(f"geocoder returned no row for {len(missing)} ids")
    return out
