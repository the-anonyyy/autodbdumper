"""multi-engine search parser — pull URLs from DDGS, Bing, Brave, Mojeek."""
from pathlib import Path
import time
from urllib.parse import urlparse

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

import requests
from bs4 import BeautifulSoup

# engine registry — parse_dorks_file(engine=...) accepts any of these;
# "both" = ddgs+bing (backward compat), "all" = every engine
ENGINES = ("ddgs", "bing", "brave", "mojeek")


class URLParser:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0 Safari/537.36")

    def parse_ddgs(self, dork: str, max_results: int = 50) -> list:
        if DDGS is None:
            self.log.warning("[parser] ddgs not installed")
            return []
        urls = []
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(dork, max_results=max_results):
                    href = r.get("href") or r.get("url")
                    if href:
                        urls.append(href)
        except Exception as e:
            self.log.warning(f"[parser] ddgs error: {e}")
        return urls

    def parse_bing(self, dork: str, pages: int = 3) -> list:
        urls = []
        for page in range(pages):
            first = page * 10 + 1
            try:
                r = requests.get(
                    "https://www.bing.com/search",
                    params={"q": dork, "first": first},
                    headers={"User-Agent": self.ua},
                    timeout=15,
                )
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("li.b_algo h2 a"):
                    href = a.get("href")
                    if href and href.startswith("http"):
                        urls.append(href)
            except Exception as e:
                self.log.warning(f"[parser] bing error page {page}: {e}")
            time.sleep(1)
        return urls

    def parse_brave(self, dork: str, pages: int = 2) -> list:
        urls = []
        for page in range(pages):
            try:
                r = requests.get(
                    "https://search.brave.com/search",
                    params={"q": dork, "offset": page},
                    headers={"User-Agent": self.ua},
                    timeout=15,
                )
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href]"):
                    href = a.get("href")
                    if (href and href.startswith("http")
                            and "brave.com" not in href):
                        urls.append(href)
            except Exception as e:
                self.log.warning(f"[parser] brave error page {page}: {e}")
            time.sleep(1)
        return urls

    def parse_mojeek(self, dork: str, pages: int = 2) -> list:
        urls = []
        for page in range(pages):
            try:
                r = requests.get(
                    "https://www.mojeek.com/search",
                    params={"q": dork, "s": page * 10 + 1},
                    headers={"User-Agent": self.ua},
                    timeout=15,
                )
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.select("a[href]"):
                    href = a.get("href")
                    if (href and href.startswith("http")
                            and "mojeek.com" not in href):
                        urls.append(href)
            except Exception as e:
                self.log.warning(f"[parser] mojeek error page {page}: {e}")
            time.sleep(1)
        return urls

    def filter_diverse(self, urls: list) -> list:
        """cap urls per registered domain; keep first-seen order."""
        try:
            pcfg = self.cfg.get("parser") or {}
            max_per = int(pcfg.get("max_per_domain", 20))
        except Exception:
            max_per = 20
        counts = {}
        kept = []
        trimmed = 0
        for u in urls:
            try:
                host = (urlparse(u).hostname or "").lower()
            except Exception:
                host = ""
            if host.startswith("www."):
                host = host[4:]
            n = counts.get(host, 0)
            if n >= max_per:
                trimmed += 1
                continue
            counts[host] = n + 1
            kept.append(u)
        self.log.info(f"[parser] domain-diversity kept={len(kept)} "
                      f"trimmed={trimmed} max_per_domain={max_per}")
        return kept

    def parse_dorks_file(self, dorks_file: str, engine: str = "both",
                         per_dork: int = 30) -> list:
        dorks = [l.strip() for l in Path(dorks_file).read_text().splitlines()
                 if l.strip()]
        self.log.info(f"[parser] {len(dorks)} dorks via {engine}")

        kill_file = self.raw / ".kill"
        out = self.raw / "urls.txt"
        all_urls = set()
        diverse = []
        try:
            for i, dork in enumerate(dorks, 1):
                if kill_file.exists():
                    kill_file.unlink(missing_ok=True)
                    self.log.warning(
                        f"[parser] /kill at {i}/{len(dorks)} — partial flush")
                    break
                if engine in ("ddgs", "both", "all"):
                    all_urls.update(self.parse_ddgs(dork, per_dork))
                if engine in ("bing", "both", "all"):
                    all_urls.update(self.parse_bing(dork, pages=2))
                if engine in ("brave", "all"):
                    all_urls.update(self.parse_brave(dork, pages=2))
                if engine in ("mojeek", "all"):
                    all_urls.update(self.parse_mojeek(dork, pages=2))
                if i % 10 == 0:
                    self.log.info(f"[parser] progress {i}/{len(dorks)} "
                                  f"urls={len(all_urls)}")
                if i % 50 == 0:
                    # partial save — /kill ke baad jitna hua utna milega
                    out.write_text("\n".join(sorted(all_urls)))
        finally:
            diverse = self.filter_diverse(sorted(all_urls))
            out.write_text("\n".join(diverse))
        self.log.info(f"[parser] {len(diverse)} urls -> {out}")
        return diverse

    def extract_param_urls(self, urls: list) -> list:
        params = [u for u in urls if "?" in u and "=" in u]
        out = self.raw / "targets.txt"
        out.write_text("\n".join(sorted(set(params))))
        self.log.info(f"[parser] {len(params)} param urls -> targets.txt")
        return params
