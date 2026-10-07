"""Stage 7 — emit final records in configured formats."""
import csv
import json
import zipfile
from pathlib import Path
from modules.notifier import Notifier


class OutputWriter:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.final = Path(cfg["paths"]["final"])
        self.oc = cfg["output"]

    def make_zip(self) -> Path:
        """bundle data/dumps/**, data/raw/sqlmap_out/** and final exports
        into data/final/bundle.zip. stdlib zipfile only."""
        self.final.mkdir(parents=True, exist_ok=True)
        zip_path = self.final / "bundle.zip"
        base = self.final / self.oc["base_name"]
        added = 0
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            dumps = Path(self.cfg["paths"]["dumps"])
            if dumps.exists():
                for f in sorted(dumps.rglob("*")):
                    if f.is_file():
                        z.write(f, f"data/dumps/{f.relative_to(dumps).as_posix()}")
                        added += 1
            sqlmap_out = self.raw / "sqlmap_out"
            if sqlmap_out.exists():
                for f in sorted(sqlmap_out.rglob("*")):
                    if f.is_file():
                        z.write(f, f"data/raw/sqlmap_out/{f.relative_to(sqlmap_out).as_posix()}")
                        added += 1
            for suffix in (".txt", ".csv", ".json"):
                f = base.with_suffix(suffix)
                if f.exists():
                    z.write(f, f"data/final/{f.name}")
                    added += 1
        self.log.info(f"[output] bundle.zip: {added} files -> {zip_path}")
        return zip_path

    def run(self):
        in_file = self.raw / "final.csv"
        if not in_file.exists():
            self.log.error("[output] no final.csv")
            return

        rows = list(csv.DictReader(in_file.open()))
        base = self.final / self.oc["base_name"]

        if "txt" in self.oc["formats"]:
            with (base.with_suffix(".txt")).open("w") as f:
                for r in rows:
                    f.write(f"{r['card']}\n")

        if "csv" in self.oc["formats"]:
            with (base.with_suffix(".csv")).open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["card", "brand", "raw_line", "source"])
                w.writeheader()
                w.writerows(rows)

        if "json" in self.oc["formats"]:
            with (base.with_suffix(".json")).open("w") as f:
                json.dump(rows, f, indent=2)

        self.log.info(f"[output] {len(rows)} records exported -> {base}.*")

        n = Notifier(self.cfg, self.log)
        n.send(f"*[output done]*\nrecords: {len(rows)}", stage="output")
        n.send_file(str(base.with_suffix(".txt")), caption="final dump")
        if self.oc.get("zip_export"):
            try:
                zp = self.make_zip()
                n.send_file(str(zp), caption="bundle.zip — dumps + results")
            except Exception as e:
                self.log.error(f"[output] zip export failed: {e}")
