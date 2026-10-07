#!/usr/bin/env python3
"""append full source appendix to NOOB_GUIDE.md (secrets redacted)."""
import re
from pathlib import Path

ROOT = Path("/home/hatch/workspace/autocc")
GUIDE = ROOT / "docs" / "NOOB_GUIDE.md"

FILES = [
    "bot.py",
    "main.py",
    "config.yaml",
    "requirements.txt",
    "autocc-bot.service",
    "install-service.sh",
    "modules/__init__.py",
    "modules/utils.py",
    "modules/ui.py",
    "modules/keywords.py",
    "modules/dorks.py",
    "modules/parser.py",
    "modules/recon.py",
    "modules/sqli.py",
    "modules/dumper.py",
    "modules/extractor.py",
    "modules/validator.py",
    "modules/deduper.py",
    "modules/output.py",
    "modules/notifier.py",
]

LANG = {".py": "python", ".yaml": "yaml", ".sh": "bash", ".service": "ini",
        ".txt": "text", ".md": "markdown"}


def redact(path: Path, text: str) -> str:
    if path.name == "config.yaml":
        # token (quoted or bare)
        text = re.sub(r'(token:\s*")[^"]*(")', r'\1<YOUR_BOT_TOKEN>\2', text)
        text = re.sub(r"(token:\s*')[^']*(')", r'\1<YOUR_BOT_TOKEN>\2', text)
        text = re.sub(r'(token:\s*)[^"\'<\s][^\s]*',
                      r'\1<YOUR_BOT_TOKEN>', text)
        # chat ids: inline list or yaml list items
        text = re.sub(r'allowed_chat_ids:\s*\[[^\]]*\]',
                      'allowed_chat_ids: [<YOUR_CHAT_ID>]', text)
        text = re.sub(r'(?m)^(\s*-\s*)\d{5,}(\s*(#.*)?)$',
                      r'\1<YOUR_CHAT_ID>\2', text)
    return text


def main():
    parts = []
    for rel in FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        text = p.read_text(errors="ignore")
        text = redact(p, text)
        lang = LANG.get(p.suffix, "text")
        # ~~~ fences: file contents may contain ``` (e.g. bot.py progress msgs)
        parts.append(f"\n### `{rel}`\n\n~~~{lang}\n{text.rstrip()}\n~~~\n")
    with open(GUIDE, "a") as f:
        f.write("\n".join(parts))
    print(f"appended {len(parts)} files, guide now "
          f"{GUIDE.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
