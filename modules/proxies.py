"""proxy pool — rotation, live-testing, and sqlmap args for the autocc bot."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests

SCHEMES = ("http", "https", "socks4", "socks5")


def _parse_line(line: str):
    """parse one proxy line -> dict, or None if blank/comment/invalid.

    formats: host:port | user:pass@host:port | http(s)://... |
             socks4://... | socks5://...
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" not in line:
        line = "http://" + line
    try:
        p = urlparse(line)
        port = p.port  # raises ValueError on garbage ports
    except Exception:
        return None
    scheme = (p.scheme or "").lower()
    if scheme not in SCHEMES or not p.hostname or not port:
        return None
    auth = ""
    if p.username:
        auth = p.username + (f":{p.password}" if p.password else "") + "@"
    return {
        "scheme": scheme,
        "host": p.hostname,
        "port": port,
        "user": p.username,
        "pass": p.password,
        "url": f"{scheme}://{p.hostname}:{port}",   # for sqlmap --proxy
        "full": f"{scheme}://{auth}{p.hostname}:{port}",  # for requests
    }


class ProxyPool:
    def __init__(self, cfg, logger):
        self.log = logger
        pc = cfg.get("proxies", {}) or {}
        self.enabled = bool(pc.get("enabled", False))
        self.file = pc.get("file", "data/proxies.txt")
        self.test_url = pc.get("test_url", "http://example.com")
        self.test_timeout = int(pc.get("test_timeout", 10))
        self.rotate_every = max(1, int(pc.get("rotate_every", 10)))
        self.raw = Path(cfg["paths"]["raw"])
        self._all = []      # every parsed proxy (dicts)
        self._live = []     # tested-good proxies (dicts)
        self._tested = False
        self._idx = 0
        self._uses = 0

    # ─── loading ──────────────────────────────────────────────────────
    def load(self):
        """read + parse the proxy file. returns list of proxy dicts."""
        self._all = []
        p = Path(self.file)
        if not p.is_absolute():
            p = Path.cwd() / p
        if not p.is_file():
            self.log.warning(f"[proxies] file not found: {p}")
            return []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            rec = _parse_line(line)
            if rec:
                self._all.append(rec)
        self.log.info(f"[proxies] loaded {len(self._all)} proxies from {p.name}")
        return self._all

    # ─── live testing ─────────────────────────────────────────────────
    def _check(self, rec):
        try:
            r = requests.get(
                self.test_url,
                proxies={"http": rec["full"], "https": rec["full"]},
                timeout=self.test_timeout,
            )
            return rec if r.status_code < 500 else None
        except Exception:
            return None

    def test_live(self, max_workers=20):
        """concurrently test every loaded proxy; survivors -> data/raw/proxies_live.txt."""
        if not self._all:
            self.load()
        live = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(self._check, rec): rec for rec in self._all}
            for f in as_completed(futs):
                rec = f.result()
                if rec:
                    live.append(rec)
        self._live = live
        self._tested = True
        self._idx = 0
        self._uses = 0
        out = self.raw / "proxies_live.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(r["full"] for r in live) + ("\n" if live else ""),
                       encoding="utf-8")
        self.log.info(f"[proxies] {len(live)}/{len(self._all)} alive -> {out}")
        return [r["full"] for r in live]

    # ─── rotation ─────────────────────────────────────────────────────
    def get(self):
        """round-robin next live proxy (auto-tests on first use). None if disabled/empty."""
        if not self.enabled:
            return None
        if not self._tested:
            self.test_live()
        if not self._live:
            return None
        if self._uses >= self.rotate_every:
            self._idx = (self._idx + 1) % len(self._live)
            self._uses = 0
        self._uses += 1
        return self._live[self._idx]["full"]

    def mark_bad(self, proxy):
        """drop a proxy from rotation (takes the full proxy URL string)."""
        before = len(self._live)
        self._live = [r for r in self._live if r["full"] != proxy]
        if len(self._live) < before:
            self.log.info(f"[proxies] removed bad proxy, {len(self._live)} live left")
            self._idx = 0
            self._uses = 0

    # ─── sqlmap integration ───────────────────────────────────────────
    def sqlmap_args(self):
        """['--proxy=<scheme://host:port>', '--proxy-cred=user:pass'?] or []."""
        cur = self.get()
        if not cur:
            return []
        p = urlparse(cur if "://" in cur else "http://" + cur)
        args = [f"--proxy={p.scheme}://{p.hostname}:{p.port}"]
        if p.username:
            cred = p.username + (f":{p.password}" if p.password else "")
            args.append(f"--proxy-cred={cred}")
        return args
