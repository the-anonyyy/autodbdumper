"""Stage 5 — Luhn + BIN validation."""
import csv
import re
from pathlib import Path
from modules.notifier import Notifier

CARD_PATTERNS = {
    "visa":       (r"^4", [13, 16, 19]),
    "mastercard": (r"^(5[1-5]|2[2-7])", [16]),
    "amex":       (r"^3[47]", [15]),
    "discover":   (r"^6(?:011|5|4[4-9]|22)", [16, 19]),
    "jcb":        (r"^35", [16, 19]),
    "diners":     (r"^3(?:0[0-5]|[68])", [14]),
    "unionpay":   (r"^62", [16, 17, 18, 19]),
}


def luhn_check(card: str) -> bool:
    digits = [int(d) for d in card]
    parity = len(digits) % 2
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def detect_brand(card: str):
    for brand, (pat, lengths) in CARD_PATTERNS.items():
        if re.match(pat, card) and len(card) in lengths:
            return brand
    return None


class Validator:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.vc = cfg["validate"]

    def run(self):
        in_file = self.raw / "parsed.csv"
        if not in_file.exists():
            self.log.error("[validate] no parsed.csv")
            return

        out_file = self.raw / "validated.csv"
        valid, rejected = [], 0
        kill_file = self.raw / ".kill"

        with in_file.open() as f:
            reader = csv.DictReader(f)
            for n, row in enumerate(reader, 1):
                if n % 2000 == 0 and kill_file.exists():
                    kill_file.unlink(missing_ok=True)
                    self.log.warning(
                        f"[validate] /kill at row {n} — partial flush")
                    break
                card = re.sub(r'\D', '', row.get("card", ""))
                if not (self.vc["min_length"] <= len(card) <= self.vc["max_length"]):
                    rejected += 1
                    continue
                brand = detect_brand(card) if self.vc["bin_check"] else "unknown"
                if not brand:
                    rejected += 1
                    continue
                if self.vc["luhn"] and not luhn_check(card):
                    rejected += 1
                    continue
                row["card"] = card
                row["brand"] = brand
                valid.append(row)

        with out_file.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["card", "brand", "raw_line", "source"])
            w.writeheader()
            w.writerows(valid)
        self.log.info(f"[validate] valid={len(valid)} rejected={rejected} -> {out_file}")

        Notifier(self.cfg, self.log).send(
            f"*[validate done]*\nvalid: {len(valid)}\nrejected: {rejected}",
            stage="validate"
        )
