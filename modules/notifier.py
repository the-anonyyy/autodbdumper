"""telegram notifier — sends stage updates to allowed chats."""
import re
import requests


def _valid_token(token: str) -> bool:
    return bool(re.match(r"^\d+:[\w-]+$", token or ""))


class Notifier:
    def __init__(self, cfg, logger):
        self.cfg = cfg
        self.log = logger
        tg = cfg.get("telegram", {})
        self.enabled = tg.get("enabled") and _valid_token(tg.get("token", ""))
        self.token = tg.get("token", "")
        self.chats = tg.get("allowed_chat_ids", [])
        self.notify_stages = tg.get("notify_stages", True)
        self.base = f"https://api.telegram.org/bot{self.token}"

    def send(self, text: str, stage: str = None):
        if not self.enabled:
            return
        if stage and not self.notify_stages:
            return
        for chat in self.chats:
            try:
                r = requests.post(
                    f"{self.base}/sendMessage",
                    json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
                    timeout=30,
                )
                if r.status_code != 200:
                    self.log.warning(f"[notify] failed {r.status_code}: {r.text[:120]}")
            except Exception as e:
                self.log.warning(f"[notify] exception: {e}")

    def send_file(self, path: str, caption: str = ""):
        if not self.enabled:
            return
        for chat in self.chats:
            try:
                with open(path, "rb") as f:
                    requests.post(
                        f"{self.base}/sendDocument",
                        data={"chat_id": chat, "caption": caption},
                        files={"document": f},
                        timeout=30,
                    )
            except Exception as e:
                self.log.warning(f"[notify] file send failed: {e}")
