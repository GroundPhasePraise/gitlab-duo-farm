"""Free proxy pool from @AlStack catalog. Geonode (pre-checked API, ~5% alive) + ProxyScrape + TheSpeedX.
Parallel batch validation. Verified live 2026-09-19."""
import random
import threading
import time
import concurrent.futures as cf

import httpx

SOURCES = [
    # (name, url, scheme)
    ("geonode_http", "https://proxylist.geonode.com/api/proxy-list?limit=60&page=1&sort_by=lastChecked&sort_type=desc&protocols=http", "http"),
    ("geonode_us", "https://proxylist.geonode.com/api/proxy-list?limit=30&page=1&sort_by=lastChecked&sort_type=desc&protocols=http&country=US", "http"),
    ("proxyscrape_http", "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxytype=http&timeout=10000", "http"),
    ("thespeedx_http", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http"),
]

_CHECK_URL = "https://gitlab.com/users/sign_in"  # check against target, not ipify — free proxies often reach ipify but not gitlab


def _parse_source(name, url, scheme, client):
    rows = []
    try:
        r = client.get(url)
        if r.status_code != 200:
            return rows
        if "geonode" in name:
            for item in r.json().get("data", []):
                rows.append((name, f"{item['ip']}:{item['port']}", scheme))
        else:
            for line in r.text.splitlines()[:400]:
                line = line.strip()
                if line.count(":") == 1 and line.split(":")[0].replace(".", "").isdigit():
                    rows.append((name, line, scheme))
    except Exception:
        pass
    return rows


def _check_one(hp, scheme, timeout=8):
    try:
        with httpx.Client(timeout=timeout, proxy=f"{scheme}://{hp}") as c:
            r = c.get(_CHECK_URL)
        return r.status_code == 200
    except Exception:
        return False


class ProxyPool:
    """ready = queue of VERIFIED working proxies (http://host:port).
    Background thread keeps it topped up."""

    def __init__(self, sources=SOURCES, target_ready=8, max_workers=24):
        self.sources = sources
        self.target_ready = target_ready
        self.max_workers = max_workers
        self.ready = []          # list of (name, proxy_url)
        self._lock = threading.Lock()
        self._dead = set()
        self._refreshing = False
        self.client = httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0"})

    def _fetch_candidates(self):
        prio, rest = [], []
        for name, url, scheme in self.sources:
            rows = [(n, hp, s) for n, hp, s in _parse_source(name, url, scheme, self.client)
                    if hp not in self._dead]
            if "geonode" in name:
                prio.extend(rows)
            else:
                rest.extend(rows)
        random.shuffle(rest)
        return (prio + rest)[:150]

    def refresh(self, max_candidates=100):
        """Fetch + parallel-check; append verified to ready. Returns ready count."""
        self._refreshing = True
        try:
            cands = self._fetch_candidates()[:max_candidates]
            with cf.ThreadPoolExecutor(self.max_workers) as ex:
                futs = {ex.submit(_check_one, hp, sch): (name, hp, sch) for name, hp, sch in cands}
                for f in cf.as_completed(futs):
                    name, hp, sch = futs[f]
                    try:
                        ok = f.result()
                    except Exception:
                        ok = False
                    if ok:
                        with self._lock:
                            if hp not in {u.rsplit("//", 1)[-1] for _, u in self.ready}:
                                self.ready.append((name, f"{sch}://{hp}"))
                    else:
                        self._dead.add(hp)
            return len(self.ready)
        finally:
            self._refreshing = False

    def next_working(self, attempts=30):
        """Pop a verified proxy; if pool empty, refresh once."""
        with self._lock:
            if self.ready:
                return self.ready.pop(0)
        self.refresh(max_candidates=80)
        with self._lock:
            if self.ready:
                return self.ready.pop(0)
        return None, None

    def next_working_batch(self, n=3):
        out = []
        for _ in range(n):
            name, px = self.next_working()
            if not px:
                break
            out.append({"proxy": px, "source": name})
        return out

    def ensure_background(self):
        """Spawn daemon thread that keeps ready >= target."""
        def loop():
            while True:
                try:
                    with self._lock:
                        need = len(self.ready) < self.target_ready and not self._refreshing
                    if need:
                        self.refresh(max_candidates=80)
                except Exception:
                    pass
                time.sleep(120)
        t = threading.Thread(target=loop, daemon=True)
        t.start()
