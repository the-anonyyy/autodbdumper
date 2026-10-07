#!/usr/bin/env python3
"""
autodump — automated recon → sqli → dump → parse → validate → dedupe → output pipeline.
Entry point. Orchestrates all modules.
"""
import argparse
import sys
from pathlib import Path

from modules.recon import Recon
from modules.sqli import SQLiScanner
from modules.dumper import Dumper
from modules.extractor import Extractor
from modules.validator import Validator
from modules.deduper import Deduper
from modules.output import OutputWriter
from modules.notifier import Notifier
from modules.utils import load_config, setup_logger, ensure_dirs


def parse_args():
    p = argparse.ArgumentParser(prog="autodump", description="automated dump pipeline")
    p.add_argument("-c", "--config", default="config.yaml", help="config path")
    p.add_argument("-t", "--target", help="single target domain")
    p.add_argument("-f", "--file", help="file with target list")
    p.add_argument("--stage", choices=["all", "recon", "sqli", "dump",
                                       "parse", "validate", "dedupe", "output",
                                       "secrets"],
                   default="all")
    p.add_argument("--mode", choices=["dump", "dbs", "tables"],
                   default="dump", help="dump mode: full dump | list DBs | list tables")
    p.add_argument("--skip-recon", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    cfg = load_config(args.config)
    logger = setup_logger(cfg["logging"]["level"], cfg["logging"]["file"])
    ensure_dirs(cfg["paths"])

    targets = []
    if args.target:
        targets.append(args.target)
    if args.file:
        targets.extend(Path(args.file).read_text().splitlines())
    targets = [t.strip() for t in targets if t.strip()]

    if not targets and stage in ("all", "recon"):
        logger.error("no targets provided")
        sys.exit(1)

    if targets:
        logger.info(f"loaded {len(targets)} targets")

    stage = args.stage

    if stage in ("all", "recon") and not args.skip_recon:
        Recon(cfg, logger).run(targets)

    if stage in ("all", "sqli"):
        SQLiScanner(cfg, logger).run()

    if stage in ("all", "dump"):
        Dumper(cfg, logger).run(mode=args.mode)

    if stage in ("all", "secrets"):
        from modules.secrets import SecretScanner
        SecretScanner(cfg, logger).scan_dir(
            Path(cfg["paths"]["dumps"]))

    if stage in ("all", "parse"):
        Extractor(cfg, logger).run()

    if stage in ("all", "validate"):
        Validator(cfg, logger).run()

    if stage in ("all", "dedupe"):
        Deduper(cfg, logger).run()

    if stage in ("all", "output"):
        OutputWriter(cfg, logger).run()

    Notifier(cfg, logger).send("*pipeline complete*")
    logger.info("pipeline complete")


if __name__ == "__main__":
    main()
