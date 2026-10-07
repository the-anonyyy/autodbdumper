"""keyword generator — build seed keyword lists for dorking."""
import itertools
import random
from pathlib import Path


NICHES = [
    "shop", "cart", "checkout", "payment", "billing",
    "login", "admin", "portal", "member", "account",
    "store", "buy", "order", "invoice", "receipt",
]

MODIFIERS = ["", "online", "pro", "beta", "dev", "test", "old", "new"]

TLDS = [".com", ".net", ".org", ".io", ".co", ".shop", ".store"]

SEPARATORS = ["-", "", "_", "."]


class KeywordGen:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])

    def generate(self, base: str, count: int = 1000) -> list:
        out = set()
        for niche, mod, tld, sep in itertools.product(NICHES, MODIFIERS, TLDS, SEPARATORS):
            kw = f"{base}{sep}{niche}"
            if mod:
                kw += f"{sep}{mod}"
            kw += tld
            out.add(kw)
            if len(out) >= count:
                break
        result = sorted(out)[:count]
        (self.raw / "keywords.txt").write_text("\n".join(result))
        self.log.info(f"[keywords] {len(result)} -> keywords.txt")
        return result
