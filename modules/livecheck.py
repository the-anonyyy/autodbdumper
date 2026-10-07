"""live-host pre-filter — drop dead targets BEFORE the slow sqlmap scan.

sqlmap wastes minutes per dead host on timeouts. This does a fast
concurrent HTTP check first, so sqlmap only sees hosts that answer.
Typical speedup: 5-10x on mixed lists. Honors data/raw/.kill.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests


class LiveCheck:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        lc = cfg.get("livecheck", {}) or {}
        self.enabled = bool(lc.get("enabled", True))
        self.timeout = int(lc.get("timeout", 8))
        self.workers = int(lc.get("workers", 50))
        self.raw = Path(cfg["paths"]["raw"])
        self.ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36")

    def _alive(self, url: str) -> bool:
        """True if the host answers HTTP (any status < 500 counts)."""
        try:
            r = requests.get(url, timeout=self.timeout,
                             allow_redirects=True,
                             headers={"User-Agent": self.ua},
                             stream=True)
            r.close()
            return r.status_code < 500
        except Exception:
            return False

    def filter(self, targets: list) -> list:
        """return only live targets; writes targets_live.txt."""
        if not self.enabled:
            return targets
        total = len(targets)
        kill_file = self.raw / ".kill"
        live = []
        done = 0
        self.log.info(f"[livecheck] checking {total} targets "
                      f"({self.workers} workers, {self.timeout}s timeout)")
        chunk = 500
        t0 = time.time()
        for start in range(0, total, chunk):
            if kill_file.exists():
                self.log.warning(f"[livecheck] /kill at {done}/{total}")
                break
            batch = targets[start:start + chunk]
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                for url, ok in zip(batch, ex.map(self._alive, batch)):
                    if ok:
                        live.append(url)
            done = min(start + chunk, total)
            self.log.info(f"[livecheck] progress {done}/{total} "
                          f"live={len(live)}")
        dt = time.time() - t0
        out = self.raw / "targets_live.txt"
        out.write_text("\n".join(live))
        self.log.info(f"[livecheck] {len(live)}/{total} alive "
                      f"in {dt:.0f}s -> {out.name}")
        return live
