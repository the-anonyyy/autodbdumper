"""Stage 1 — reconnaissance. subdomain enum, live host check, crawl, param discovery."""
from pathlib import Path
import re
from modules.utils import run, which
from modules.notifier import Notifier


class Recon:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.rc = cfg["recon"]

    def run(self, targets: list):
        self.log.info(f"[recon] starting for {len(targets)} targets")
        all_subs = set()
        for t in targets:
            subs = self._subfinder(t)
            all_subs.update(subs)

        subs_file = self.raw / "subs.txt"
        subs_file.write_text("\n".join(sorted(all_subs)))
        self.log.info(f"[recon] {len(all_subs)} subdomains -> {subs_file}")

        live = self._httpx(subs_file)
        live_file = self.raw / "live.txt"
        live_file.write_text("\n".join(live))
        self.log.info(f"[recon] {len(live)} live hosts -> {live_file}")

        urls = self._katana(live_file)
        urls_file = self.raw / "urls.txt"
        urls_file.write_text("\n".join(urls))

        targets_file = self.raw / "targets.txt"
        params = self._extract_params(urls)
        targets_file.write_text("\n".join(params))
        self.log.info(f"[recon] {len(params)} param'd urls -> {targets_file}")

        Notifier(self.cfg, self.log).send(
            f"*[recon done]*\nsubs: {len(all_subs)}\nlive: {len(live)}\ntargets: {len(params)}",
            stage="recon"
        )

    def _subfinder(self, domain: str) -> list:
        if not which("subfinder"):
            self.log.warning("[recon] subfinder not found, skipping")
            return []
        rc, out, err = run(["subfinder", "-d", domain, "-silent"],
                           logger=self.log)
        if rc != 0:
            self.log.warning(f"[recon] subfinder failed for {domain}")
            return []
        return [l.strip() for l in out.splitlines() if l.strip()]

    def _httpx(self, subs_file: Path) -> list:
        if not which("httpx"):
            self.log.warning("[recon] httpx not found, using subs as-is")
            return subs_file.read_text().splitlines()
        rc, out, err = run(
            ["httpx", "-l", str(subs_file), "-silent", "-no-color"],
            logger=self.log,
        )
        if rc != 0:
            return []
        return [l.strip() for l in out.splitlines() if l.strip()]

    def _katana(self, live_file: Path) -> list:
        if not which("katana"):
            self.log.warning("[recon] katana not found, skipping crawl")
            return []
        rc, out, err = run(
            ["katana", "-list", str(live_file),
             "-d", str(self.rc["katana_depth"]),
             "-jc", "-kf", "all", "-silent"],
            logger=self.log,
        )
        if rc != 0:
            return []
        return [l.strip() for l in out.splitlines() if l.strip()]

    def _extract_params(self, urls: list) -> list:
        seen = set()
        out = []
        for u in urls:
            if "?" not in u:
                continue
            if u in seen:
                continue
            seen.add(u)
            out.append(u)
        return out
