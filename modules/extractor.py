"""Stage 4 — parse raw dumps into structured records."""
import csv
import re
from pathlib import Path
from modules.notifier import Notifier

CARD_RE = re.compile(r'(?:\d[ -]*?){13,19}')
EXP_RE = re.compile(r'\b(0[1-9]|1[0-2])[/\-\s]?(\d{2}|\d{4})\b')


class Extractor:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.dumps = Path(cfg["paths"]["dumps"])
        self.raw = Path(cfg["paths"]["raw"])
        self.exts = tuple(cfg["extract"]["extensions"])

    def run(self):
        out_file = self.raw / "parsed.csv"
        records = []
        for f in self.dumps.rglob("*"):
            if f.is_file() and f.suffix.lower() in self.exts:
                records.extend(self._parse_file(f))
        with out_file.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["card", "raw_line", "source"])
            w.writeheader()
            w.writerows(records)
        self.log.info(f"[extract] {len(records)} candidates -> {out_file}")

        Notifier(self.cfg, self.log).send(
            f"*[extract done]*\ncandidates: {len(records)}",
            stage="parse"
        )

    def _parse_file(self, path: Path):
        out = []
        try:
            text = path.read_text(errors="ignore")
        except Exception:
            return out
        for line in text.splitlines():
            for match in CARD_RE.findall(line):
                digits = re.sub(r'\D', '', match)
                if 13 <= len(digits) <= 19:
                    out.append({
                        "card": digits,
                        "raw_line": line.strip()[:200],
                        "source": str(path),
                    })
        return out
