"""Stage 6 — deduplication + BIN grouping."""
import csv
from pathlib import Path
from modules.notifier import Notifier


class Deduper:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.dc = cfg["dedupe"]

    def run(self):
        in_file = self.raw / "validated.csv"
        if not in_file.exists():
            self.log.error("[dedupe] no validated.csv")
            return

        out_file = self.raw / "final.csv"
        seen = set()
        unique = []
        bins = {}
        kill_file = self.raw / ".kill"

        with in_file.open() as f:
            reader = csv.DictReader(f)
            for n, row in enumerate(reader, 1):
                if n % 2000 == 0 and kill_file.exists():
                    kill_file.unlink(missing_ok=True)
                    self.log.warning(
                        f"[dedupe] /kill at row {n} — partial flush")
                    break
                card = row["card"]
                if card in seen:
                    continue
                seen.add(card)
                unique.append(row)
                b = card[:6]
                bins[b] = bins.get(b, 0) + 1

        with out_file.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["card", "brand", "raw_line", "source"])
            w.writeheader()
            w.writerows(unique)

        self.log.info(f"[dedupe] unique={len(unique)} -> {out_file}")

        if self.dc.get("bin_report"):
            bin_file = self.raw / "bin_report.csv"
            with bin_file.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["bin", "count"])
                for b, c in sorted(bins.items(), key=lambda x: -x[1]):
                    w.writerow([b, c])
            self.log.info(f"[dedupe] bin report -> {bin_file}")

        Notifier(self.cfg, self.log).send(
            f"*[dedupe done]*\nunique: {len(unique)}",
            stage="dedupe"
        )
