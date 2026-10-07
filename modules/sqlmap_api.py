"""sqlmap REST API wrapper — drives sqlmapapi.py for live per-task scans.

Uses the stock sqlmapapi HTTP API (no patches needed):
  GET  /task/new             -> {"taskid": ...}
  POST /scan/<id>/start      (json: url + options)
  POST /option/<id>/set      (json: options)
  GET  /scan/<id>/status|data|log|stop
  GET  /task/<id>/delete
"""
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import requests


class SqlmapAPI:
    def __init__(self, cfg, logger):
        self.log = logger
        sc = cfg.get("sqlmapapi", {}) or {}
        self.enabled = bool(sc.get("enabled", False))
        self.host = sc.get("host", "127.0.0.1")
        self.port = int(sc.get("port", 8775))
        # sqlmap >= 1.10 mandates --username/--password for the REST server.
        # no hardcoded default: use config value, else a random per-run
        # password (localhost only — never expose this port).
        self.username = sc.get("username", "autodump")
        self.password = sc.get("password") or secrets.token_urlsafe(24)
        self.base = f"http://{self.host}:{self.port}"
        self.api_path = self._locate(cfg)
        self._proc = None

    # ─── locate sqlmapapi.py next to sqlmap_bin ───────────────────────
    def _locate(self, cfg):
        cands = []
        bin_path = (cfg.get("sqli", {}) or {}).get("sqlmap_bin", "")
        if bin_path:
            real = os.path.realpath(bin_path)
            cands.append(os.path.join(os.path.dirname(real), "sqlmapapi.py"))
            cands.append(os.path.join(os.path.dirname(os.path.abspath(bin_path)),
                                      "sqlmapapi.py"))
            try:  # wrapper script may exec /path/to/sqlmap.py — derive its dir
                text = Path(bin_path).read_text(encoding="utf-8", errors="replace")
                m = re.search(r"([\w\-./~$]+sqlmap\.py)", text)
                if m:
                    d = os.path.dirname(
                        m.group(1).replace("$HOME", os.path.expanduser("~")))
                    cands.append(os.path.join(d, "sqlmapapi.py"))
            except OSError:
                pass
        cands.append("/home/hatch/workspace/sqlmap/sqlmapapi.py")
        for c in cands:
            if c and os.path.isfile(c):
                self.log.info(f"[sqlmapapi] found: {c}")
                return c
        self.log.warning("[sqlmapapi] sqlmapapi.py not found")
        return None

    # ─── server lifecycle ─────────────────────────────────────────────
    def _is_up(self):
        try:
            requests.get(self.base + "/", timeout=2,
                         auth=(self.username, self.password))
            return True  # any HTTP answer (even 401/404) means the server is up
        except requests.RequestException:
            return False

    def start_server(self):
        """start `sqlmapapi.py -s` if needed; wait up to 20s. raises RuntimeError on failure."""
        if not self.enabled:
            self.log.info("[sqlmapapi] disabled in config")
            return False
        if self._is_up():
            self.log.info(f"[sqlmapapi] already running at {self.base}")
            return True
        if not self.api_path:
            raise RuntimeError(
                "[sqlmapapi] enabled but sqlmapapi.py not found "
                "next to sqli.sqlmap_bin")
        cmd = [sys.executable, self.api_path, "-s",
               "-H", self.host, "-p", str(self.port),
               "--username", self.username, "--password", self.password]
        self.log.info(f"[sqlmapapi] starting: {' '.join(cmd[:6])} ...")
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        deadline = time.time() + 20
        while time.time() < deadline:
            if self._is_up():
                self.log.info(f"[sqlmapapi] up at {self.base} (pid {self._proc.pid})")
                return True
            if self._proc.poll() is not None:
                raise RuntimeError(
                    f"[sqlmapapi] server exited (rc={self._proc.returncode})")
            time.sleep(1)
        raise RuntimeError(f"[sqlmapapi] no answer at {self.base} within 20s")

    def shutdown(self):
        """stop the server process we started (if any)."""
        if self._proc and self._proc.poll() is None:
            self.log.info("[sqlmapapi] stopping server")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
            return True
        return False

    # ─── http helpers ─────────────────────────────────────────────────
    def _auth(self):
        return (self.username, self.password)

    def _get(self, path):
        r = requests.get(self.base + path, timeout=15, auth=self._auth())
        r.raise_for_status()
        return r.json()

    def _post(self, path, payload):
        r = requests.post(self.base + path, json=payload, timeout=15,
                          auth=self._auth())
        r.raise_for_status()
        return r.json()

    # ─── task API ─────────────────────────────────────────────────────
    def new_task(self):
        """create a task -> taskid (or None)."""
        try:
            return self._get("/task/new").get("taskid")
        except Exception as e:
            self.log.warning(f"[sqlmapapi] new_task failed: {e}")
            return None

    def set_options(self, taskid, opts: dict):
        try:
            return bool(self._post(f"/option/{taskid}/set", opts).get("success", True))
        except Exception as e:
            self.log.warning(f"[sqlmapapi] set_options failed: {e}")
            return False

    def start_scan(self, taskid):
        try:
            return bool(self._post(f"/scan/{taskid}/start", {}).get("success", False))
        except Exception as e:
            self.log.warning(f"[sqlmapapi] start_scan failed: {e}")
            return False

    def status(self, taskid):
        """'running' | 'terminated' | ..."""
        try:
            return self._get(f"/scan/{taskid}/status").get("status", "unknown")
        except Exception:
            return "unknown"

    def scan_log(self, taskid):
        """list of log entries (named scan_log: self.log is the logger)."""
        try:
            return self._get(f"/scan/{taskid}/log").get("log", [])
        except Exception:
            return []

    def data(self, taskid):
        try:
            return self._get(f"/scan/{taskid}/data")
        except Exception:
            return {}

    def stop_scan(self, taskid):
        try:
            self._get(f"/scan/{taskid}/stop")
            return True
        except Exception:
            return False

    def delete_task(self, taskid):
        try:
            self._get(f"/task/{taskid}/delete")
            return True
        except Exception:
            return False

    # ─── full lifecycle ───────────────────────────────────────────────
    @staticmethod
    def _is_injectable(data, entries):
        for e in entries or []:
            msg = e.get("message", "") if isinstance(e, dict) else str(e)
            if "injectable" in msg.lower():
                return True

        def walk(o):
            if isinstance(o, dict):
                keys = {str(k).lower() for k in o}
                if {"parameter", "place"} <= keys or "ptype" in keys:
                    return True
                return any(walk(v) for v in o.values())
            if isinstance(o, (list, tuple)):
                return any(walk(v) for v in o)
            return False

        return walk(data)

    def scan_target(self, url, options: dict = None):
        """new_task -> set url+options -> start -> poll every 3s -> data+log.

        returns {"url": url, "injectable": bool, "data": {...}}.
        raises RuntimeError if the server can't be started / no task created.
        """
        options = dict(options or {})
        self.start_server()
        taskid = self.new_task()
        if not taskid:
            raise RuntimeError("[sqlmapapi] could not create task")
        try:
            opts = {"url": url}
            opts.update(options)
            self.set_options(taskid, opts)
            if not self.start_scan(taskid):
                # fallback: start with options inline in one call
                self._post(f"/scan/{taskid}/start", opts)
            while True:
                st = self.status(taskid)
                self.log.info(f"[sqlmapapi] {url} -> {st}")
                if st == "terminated":
                    break
                time.sleep(3)
            data = self.data(taskid)
            entries = self.scan_log(taskid)
            return {"url": url,
                    "injectable": self._is_injectable(data, entries),
                    "data": data}
        finally:
            self.delete_task(taskid)
