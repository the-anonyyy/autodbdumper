"""Stage 2 — sqli scan. wraps sqlmap against target list (batched).

Two engines:
  - CLI mode (default): sqlmap -m <batch file>, BATCH=50 per run.
  - sqlmap REST API mode (cfg["sqlmapapi"]["enabled"]): one api task per
    target via modules.sqlmap_api.SqlmapAPI; falls back to CLI on failure.
    Injectable urls come from the API return value; the output-dir scan is
    a secondary source (also covers cfg["sqlmapapi"]["output_dir"]).
"""
import hashlib
import json
import re
import signal
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from modules.utils import which
from modules.notifier import Notifier

BATCH = 50  # targets per sqlmap run — progress + /kill granularity

# file text matching any alternative => the file declares an injection
# point, so every http(s) token inside it is an injectable-url candidate
INJECTABLE_RE = re.compile(
    r"is .{0,80}injectable|identified the following injection point"
    r"|appears to be injectable",
    re.I,
)


class _Terminated(BaseException):
    """SIGTERM (/kill force) — BaseException taaki `except Exception`
    wale handlers (API->CLI fallback) isko na pakad lein."""


def _fmt_dur(s):
    s = int(max(0, s))
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


class SQLiScanner:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        self.raw = Path(cfg["paths"]["raw"])
        self.rc = cfg["sqli"]

    @staticmethod
    def collect_injectables(out_dir: Path) -> set:
        """scan sqlmap output dir for injectable urls (works on partial runs)."""
        injectables = set()
        if not out_dir.exists():
            return injectables
        for f in out_dir.rglob("*"):
            if not f.is_file():
                continue
            try:
                txt = f.read_text(errors="ignore")
            except Exception:
                continue
            # legacy heuristic: "Parameter:" line containing an http token
            for line in txt.splitlines():
                if "Parameter:" in line and "http" in line:
                    for token in line.split():
                        if token.startswith("http"):
                            injectables.add(token)
            # stronger heuristic: file declares an injection point ->
            # every http(s) token in the file is a candidate target url
            if INJECTABLE_RE.search(txt):
                for token in re.split(r"\s+", txt):
                    token = token.strip("\"'(),;")
                    if token.startswith(("http://", "https://")):
                        injectables.add(token)
        return injectables

    def _collect_all(self, out_dir: Path) -> set:
        """union of CLI out dir + optional sqlmapapi output dir."""
        found = set(self.collect_injectables(out_dir))
        api_out = (self.cfg.get("sqlmapapi", {}) or {}).get("output_dir")
        if api_out:
            found |= self.collect_injectables(Path(api_out))
        return found

    # ─── resume checkpoint ──────────────────────────────────────────
    # har target/batch ke baad progress disk pe save — /kill ya VM restart
    # ke baad dobara wahi file bhejne par scan wahin se continue hoga.
    def _ckpt_path(self):
        return self.raw / ".sqli_checkpoint.json"

    @staticmethod
    def _targets_hash(targets):
        return hashlib.sha256("\n".join(targets).encode()).hexdigest()[:16]

    def _load_checkpoint(self, targets):
        p = self._ckpt_path()
        if not p.exists():
            return set(), set()
        try:
            cp = json.loads(p.read_text())
        except Exception:
            return set(), set()
        if cp.get("targets_hash") != self._targets_hash(targets):
            self.log.info("[sqli] targets changed — fresh scan")
            return set(), set()
        tset = set(targets)
        done = set(cp.get("done", [])) & tset
        found = set(cp.get("found", [])) & tset
        if done:
            self.log.info(f"[sqli] resume: skipping {len(done)} done, "
                          f"{len(found)} injectables kept")
        return done, found

    def _save_checkpoint(self):
        try:
            p = self._ckpt_path()
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({
                "targets_hash": self._targets_hash(self._ckpt_targets),
                "done": sorted(self._ckpt_done),
                "found": sorted(self._ckpt_found),
            }))
            tmp.replace(p)
        except Exception as e:
            self.log.warning(f"[sqli] checkpoint save failed: {e}")

    def _clear_checkpoint(self):
        self._ckpt_path().unlink(missing_ok=True)

    def _eta_str(self, done, total):
        """elapsed + ETA — live info ke liye progress line mein."""
        el = time.time() - self._t0
        scanned = done - self._offset0
        if scanned <= 0 or done >= total:
            return f"elapsed={_fmt_dur(el)}"
        eta = el / scanned * (total - done)
        return f"elapsed={_fmt_dur(el)} eta={_fmt_dur(eta)}"

    @staticmethod
    def _domain(url):
        try:
            return urlsplit(url).netloc or url[:40]
        except Exception:
            return url[:40]

    def _proxy_cli_args(self):
        """optional proxy rotation — never crash if module is missing."""
        try:
            from modules.proxies import ProxyPool
            return ProxyPool(self.cfg, self.log).sqlmap_args()
        except Exception:
            return []

    def _proxy_api_opts(self):
        """proxy options for the REST API (derived from ProxyPool)."""
        try:
            from modules.proxies import ProxyPool
            pool = ProxyPool(self.cfg, self.log)
            if hasattr(pool, "api_options"):
                return dict(pool.api_options())
            opts = {}
            args = pool.sqlmap_args()
            for i in range(len(args)):
                a = args[i]
                if a == "--proxy" and i + 1 < len(args):
                    opts["proxy"] = args[i + 1]
                elif a.startswith("--proxy="):
                    opts["proxy"] = a.split("=", 1)[1]
                elif a.startswith("--proxy-cred="):
                    opts["proxyCred"] = a.split("=", 1)[1]
            return opts
        except Exception:
            return {}

    def _base_cmd(self, out_dir: Path):
        cmd = [
            self.rc["sqlmap_bin"],
            "--batch",
            f"--level={self.rc['level']}",
            f"--risk={self.rc['risk']}",
            f"--threads={self.rc['threads']}",
            f"--technique={self.rc['technique']}",
            f"--tamper={self.rc['tamper']}",
            f"--output-dir={out_dir}",
            "--flush-session",
        ]
        if self.rc.get("random_agent"):
            cmd.append("--random-agent")
        if self.rc.get("delay"):
            cmd.append(f"--delay={self.rc['delay']}")
        cmd += self._proxy_cli_args()
        return cmd

    # ---------------------------------------------------------------- CLI
    def _run_cli_mode(self, targets, offset, total, out_dir, kill_file,
                      batch_file, sqlmap_log):
        """CLI engine over targets list; offset = already-completed count."""
        for start in range(0, len(targets), BATCH):
            if kill_file.exists():
                kill_file.unlink(missing_ok=True)
                self.log.warning(
                    f"[sqli] /kill at {offset + start}/{total} — partial results")
                self._killed = True
                self._save_checkpoint()
                break
            chunk = targets[start:start + BATCH]
            batch_file.write_text("\n".join(chunk))
            cmd = self._base_cmd(out_dir) + ["-m", str(batch_file)]
            self.log.info(
                f"[sqli] batch {offset + start + 1}-{offset + start + len(chunk)}/{total}")
            try:
                with open(sqlmap_log, "w") as lf:
                    proc = subprocess.Popen(
                        cmd, stdout=lf, stderr=subprocess.STDOUT, text=True)
                    self._child_proc = proc
                    while proc.poll() is None:
                        if kill_file.exists():
                            self.log.warning("[sqli] /kill — stopping sqlmap")
                            proc.terminate()
                            try:
                                proc.wait(timeout=15)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                            break
                        time.sleep(1)
                    self._child_proc = None
            except Exception as e:
                self._child_proc = None
                self.log.error(f"[sqli] batch failed: {e}")
            if kill_file.exists():
                kill_file.unlink(missing_ok=True)
                self._killed = True
                self._save_checkpoint()
                break
            done = offset + min(start + BATCH, len(targets))
            self._ckpt_done.update(chunk)
            self._ckpt_found |= self._collect_all(out_dir)
            self._save_checkpoint()
            n_inj = len(self._ckpt_found)
            self.log.info(
                f"[sqli] progress {done}/{total} injectables={n_inj} "
                f"{self._eta_str(done, total)}")

    # ------------------------------------------------------------ API mode
    def _run_api_mode(self, targets, offset, total, out_dir, kill_file,
                      batch_file, sqlmap_log):
        """sqlmap REST API engine: one task per target.

        Returns (handled, api_found): handled=False => caller must run full
        CLI mode; api_found = urls the API itself flagged injectable (the
        api server writes to its own output dir, so we track these directly).
        """
        try:
            from modules.sqlmap_api import SqlmapAPI
        except Exception as e:
            self.log.warning(
                f"[sqli] sqlmap_api module unavailable ({e}) — CLI mode")
            return False, set()
        try:
            api = SqlmapAPI(self.cfg, self.log)
        except Exception as e:
            self.log.warning(f"[sqli] SqlmapAPI init failed: {e} — CLI mode")
            return False, set()

        opts = {
            "level": self.rc["level"],
            "risk": self.rc["risk"],
            "technique": self.rc["technique"],
            "tamper": self.rc["tamper"],
            "randomAgent": bool(self.rc.get("random_agent")),
            "batch": True,
        }
        opts.update(self._proxy_api_opts())

        api_found = set()
        done = offset
        for url in targets:
            if kill_file.exists():
                kill_file.unlink(missing_ok=True)
                self.log.warning(
                    f"[sqli] /kill at {done}/{total} — partial results")
                self._killed = True
                self._save_checkpoint()
                return True, api_found
            self.log.info(f"[sqli] ▶ {done + 1}/{total} {self._domain(url)}")
            try:
                res = api.scan_target(url, opts)
                if isinstance(res, dict) and res.get("injectable"):
                    api_found.add(url)
                    self._ckpt_found.add(url)
            except Exception as e:
                self.log.warning(
                    f"[sqli] sqlmapapi error on target {done + 1}: {e} — "
                    f"CLI fallback for remaining {total - done}")
                self._save_checkpoint()
                self._run_cli_mode(targets[done - offset:], done, total,
                                   out_dir, kill_file, batch_file, sqlmap_log)
                return True, api_found
            done += 1
            self._ckpt_done.add(url)
            if done % 5 == 0:
                self._save_checkpoint()
            n_inj = len(api_found | self._ckpt_found
                        | self._collect_all(out_dir))
            self.log.info(
                f"[sqli] progress {done}/{total} injectables={n_inj} "
                f"{self._eta_str(done, total)}")
        self._save_checkpoint()
        return True, api_found

    # ------------------------------------------------------------------ run
    def run(self):
        targets_file = self.raw / "targets.txt"
        if not targets_file.exists():
            self.log.error("[sqli] no targets.txt — run recon first")
            return

        if not which(self.rc["sqlmap_bin"]):
            self.log.error(f"[sqli] {self.rc['sqlmap_bin']} not found in PATH")
            return

        targets = [t.strip() for t in targets_file.read_text().splitlines()
                   if t.strip()]
        if not targets:
            self.log.error("[sqli] targets.txt is empty")
            return

        out_dir = self.raw / "sqlmap_out"
        out_dir.mkdir(exist_ok=True)
        kill_file = self.raw / ".kill"
        batch_file = self.raw / ".sqli_batch.txt"
        sqlmap_log = self.raw / "sqlmap_progress.log"

        total = len(targets)
        self.log.info(f"[sqli] {total} targets loaded")

        # live-host pre-filter: dead hosts pe sqlmap ka timeout-wait bekar hai
        from modules.livecheck import LiveCheck
        targets = LiveCheck(self.cfg, self.log).filter(targets)
        if not targets:
            self.log.error("[sqli] no live targets after pre-filter")
            return
        total = len(targets)
        self.log.info(f"[sqli] scanning {total} live targets, {BATCH}/batch")

        # resume checkpoint: pichhli run jahan ruki thi wahan se continue
        self._ckpt_targets = targets
        self._ckpt_done, self._ckpt_found = self._load_checkpoint(targets)
        self._killed = False
        self._child_proc = None
        self._t0 = time.time()
        remaining = [t for t in targets if t not in self._ckpt_done]
        offset = len(self._ckpt_done)
        self._offset0 = offset

        # SIGTERM (/kill force) bhi graceful: checkpoint + partial file save
        def _on_term(signum, frame):
            raise _Terminated()
        signal.signal(signal.SIGTERM, _on_term)

        api_cfg = self.cfg.get("sqlmapapi", {}) or {}
        api_found = set()
        try:
            if not remaining:
                self.log.info("[sqli] all targets already done — nothing to scan")
            elif api_cfg.get("enabled"):
                self.log.info("[sqli] engine: sqlmap REST API")
                handled, api_found = self._run_api_mode(
                    remaining, offset, total, out_dir, kill_file,
                    batch_file, sqlmap_log)
                if not handled:
                    self._run_cli_mode(remaining, offset, total, out_dir,
                                       kill_file, batch_file, sqlmap_log)
            else:
                self._run_cli_mode(remaining, offset, total, out_dir, kill_file,
                                   batch_file, sqlmap_log)
        except _Terminated:
            self._killed = True
            self.log.warning("[sqli] SIGTERM — saving partial state")
            child = self._child_proc
            if child is not None and child.poll() is None:
                try:
                    child.terminate()
                except Exception:
                    pass

        self._save_checkpoint()
        batch_file.unlink(missing_ok=True)
        found = self._collect_all(out_dir) | api_found | self._ckpt_found
        (self.raw / "injectable.txt").write_text("\n".join(sorted(found)))
        if self._killed:
            self.log.info(f"[sqli] stopped — resume point saved "
                          f"({len(self._ckpt_done)}/{total} done)")
        else:
            self._clear_checkpoint()
            self.log.info(f"[sqli] done — {len(found)} injectables -> injectable.txt")

        Notifier(self.cfg, self.log).send(
            f"*[sqli done]*\ninjectables: {len(found)}",
            stage="sqli"
        )
