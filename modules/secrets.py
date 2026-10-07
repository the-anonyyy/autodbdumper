"""leaked-secret scanner — API keys / tokens / private keys in dump files.

Defensive purpose: find accidentally exposed credentials in data you are
authorized to audit. Deliberately NO card-number / CVV / expiry / password
patterns here.
"""
import json
import re
from pathlib import Path


PATTERNS = {
    "aws_access": re.compile(r"AKIA[0-9A-Z]{16}"),
    "aws_secret": re.compile(
        r"(?i)aws(.{0,20})?(secret|access).{0,20}?[\"']([A-Za-z0-9/+=]{40})[\"']"),
    "stripe": re.compile(r"sk_(live|test)_[0-9a-zA-Z]{24,}"),
    "gcp_key": re.compile(r"AIza[0-9A-Za-z\-_]{35}"),
    "sendgrid": re.compile(r"SG\.[0-9A-Za-z\-_]{22}\.[0-9A-Za-z\-_]{43}"),
    "github_pat": re.compile(r"ghp_[0-9A-Za-z]{36}"),
    "gitlab_pat": re.compile(r"glpat-[0-9A-Za-z\-_]{20,}"),
    "slack_token": re.compile(r"xox[baprs]-[0-9A-Za-z\-]{10,}"),
    "twilio": re.compile(r"SK[0-9a-fA-F]{32}"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    "private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    "generic_api_key": re.compile(
        r"(?i)(api[_-]?key|apikey)[\"'\s:=]{1,20}([A-Za-z0-9_\-]{16,64})"),
}


def _redact(s: str) -> str:
    """first4...last4 (never write full secrets to the report)."""
    s = str(s)
    return s[:4] + "..." + s[-4:] if len(s) > 8 else s[:2] + "..." + s[-2:]


class SecretScanner:
    def __init__(self, cfg, logger):
        self.log = logger
        self.enabled = bool((cfg.get("secrets", {}) or {}).get("enabled", False))
        self.raw = Path(cfg["paths"]["raw"])

    def scan_text(self, text: str) -> dict:
        """{pattern_name: [unique matches]}."""
        out = {}
        for name, rx in PATTERNS.items():
            matches = rx.findall(text)
            if not matches:
                continue
            flat = []
            for m in matches:
                if isinstance(m, tuple):
                    flat.append("|".join(str(x) for x in m if x))
                else:
                    flat.append(m)
            seen, uniq = set(), []
            for v in flat:
                if v not in seen:
                    seen.add(v)
                    uniq.append(v)
            out[name] = uniq
        return out

    def scan_file(self, path) -> dict:
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            self.log.warning(f"[secrets] cannot read {p}: {e}")
            return {}
        return self.scan_text(text)

    def scan_dir(self, dir, exts=(".txt", ".csv", ".sql", ".log")) -> dict:
        """scan every matching file; redacted findings -> data/raw/secrets_found.json."""
        root = Path(dir)
        files = [f for f in root.rglob("*")
                 if f.is_file() and f.suffix.lower() in exts]
        findings, details = {}, []
        for f in sorted(files):
            for name, matches in self.scan_file(f).items():
                findings[name] = findings.get(name, 0) + len(matches)
                for m in matches:
                    details.append({"file": str(f), "type": name,
                                    "match": _redact(m)})
        report = {"files_scanned": len(files),
                  "findings": findings,
                  "details": details}
        out = self.raw / "secrets_found.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.log.info(f"[secrets] {len(files)} files, "
                      f"{sum(findings.values())} findings -> {out}")
        return report
