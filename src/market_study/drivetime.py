"""Drive times from each example site to many points, via the public OSRM demo server.

OSRM routes on OpenStreetMap at free-flow speeds: no traffic, no time of day. Results
are cached so the public server is asked once per chunk.
"""
import hashlib
import json
import time

from .config import OSRM_TABLE, RAW
from .fetch import _get


def table(sources, destinations, chunk=90):
    """sources, destinations: lists of (lat, lon). Returns (minutes, km, snap_m) as
    lists of rows, one row per source, one column per destination; None where unroutable."""
    n_src = len(sources)
    minutes = [[None] * len(destinations) for _ in sources]
    km = [[None] * len(destinations) for _ in sources]
    snap = [None] * len(destinations)
    for start in range(0, len(destinations), chunk):
        dest = destinations[start:start + chunk]
        coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in list(sources) + list(dest))
        url = (OSRM_TABLE + coords + "?sources=" + ";".join(map(str, range(n_src)))
               + "&destinations=" + ";".join(str(n_src + j) for j in range(len(dest)))
               + "&annotations=duration,distance")
        cache = RAW / "osrm" / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
        if cache.exists():
            d = json.loads(cache.read_text())
        else:
            d = _get(url).json()
            if d.get("code") != "Ok":
                raise RuntimeError(f"OSRM: {d.get('code')} {d.get('message')}")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(d))
            time.sleep(1.1)  # the demo server's usage policy: at most one request a second
        for i in range(n_src):
            for j in range(len(dest)):
                s = d["durations"][i][j]
                m = d["distances"][i][j]
                minutes[i][start + j] = None if s is None else s / 60
                km[i][start + j] = None if m is None else m / 1000
        for j, w in enumerate(d["destinations"]):
            snap[start + j] = w.get("distance")
    return minutes, km, snap
