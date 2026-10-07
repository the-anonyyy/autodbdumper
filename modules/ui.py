"""reply-keyboard menus only. no inline menus. chat = pure output."""
from telegram import ReplyKeyboardMarkup, KeyboardButton


def _kb(rows):
    """rows: list of lists of strings"""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(t) for t in row] for row in rows],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


# ─── MAIN ─────────────────────────────────────────────────────────────
MAIN = _kb([
    ["🔑 Generate Keywords", "🎯 Generate Dorks"],
    ["🌐 Parse Dorks → URLs", "💉 SQLi Scanner"],
    ["📦 DB Dump", "📄 Validate"],
    ["🧹 Dedupe", "📤 Output Files"],
    ["🚀 Full Auto Pipeline", "📊 Status"],
    ["📥 Fetch Results", "🛠 Help"],
])


# ─── SUBMENUS ─────────────────────────────────────────────────────────
KW = _kb([
    ["🔑 100", "🔑 500", "🔑 1000"],
    ["🔑 5000", "🔑 10000", "✏️ Custom Base"],
    ["⬅️ Back"],
])

DORK = _kb([
    ["🌐 Generic Dorks", "💉 SQLi Dorks"],
    ["📁 File Dorks", "🧩 CMS Dorks"],
    ["🌍 Country Dorks", "🌟 ALL Dorks Pro"],
    ["⬅️ Back"],
])

PARSE = _kb([
    ["🦆 DDGS only", "🔵 Bing only"],
    ["⚡ DDGS + Bing", "📂 Pick Dork File"],
    ["⬅️ Back"],
])

SQLI = _kb([
    ["🚀 Scan targets.txt"],
    ["⚙️ Level 1", "⚙️ Level 2", "⚙️ Level 3"],
    ["🎭 Tamper: ON", "🕵️ UA: ON"],
    ["🌐 Proxy: OFF", "🔌 API: OFF"],
    ["📤 Upload Proxies"],
    ["⬅️ Back"],
])

DUMP = _kb([
    ["📦 Dump target_db.cards"],
    ["📋 List DBs", "🗂 List Tables"],
    ["📊 Custom Table", "🕵 Secrets Scan"],
    ["⬅️ Back"],
])

VALIDATE = _kb([
    ["✅ Run Validate"],
    ["⬅️ Back"],
])

DEDUPE = _kb([
    ["🧹 Run Dedupe"],
    ["⬅️ Back"],
])

OUTPUT = _kb([
    ["📄 .txt", "📊 .csv", "🧾 .json"],
    ["📦 All Formats"],
    ["⬅️ Back"],
])

AUTO = _kb([
    ["🎯 From Domain", "🌐 From Dorks"],
    ["🔗 From URL List"],
    ["⬅️ Back"],
])

STATUS = _kb([
    ["🔄 Refresh", "📈 Full Report"],
    ["🗑 Remove Files"],
    ["⬅️ Back"],
])

FETCH = _kb([
    ["📄 output.txt", "📊 output.csv"],
    ["🧾 output.json", "📦 Send All"],
    ["⬅️ Back"],
])

HELP = _kb([
    ["🔑 Keywords", "🎯 Dorks"],
    ["🌐 Parser", "💉 SQLi"],
    ["📦 Dump", "✅ Validate"],
    ["🧹 Dedupe", "📤 Output"],
    ["⬅️ Back"],
])


# progress bar helper (used in chat only)
def bar(pct, width=18):
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled) + f"  {pct}%"


# ─── SCREEN TEXT (sent as chat msg, one-time header) ──────────────────
HEADER_MAIN = (
    "🪱 *What Can Auto Dump Do?*\n\n"
    "🥇 GEN KEYWORDS   ⇔  keyword sets\n"
    "🥈 GEN DORKS      ⇔  multi-category dorks\n"
    "🥉 DEEP PARSER    ⇔  DDGS + Bing\n"
    "🌟 DORKS PRO      ⇔  HQ SQLi templates\n"
    "💉 SQLI SCANNER   ⇔  sqlmap\n"
    "🏗  DORKS ⇔ DUMP  ⇔  full chain\n"
    "🔗 URLS ⇔ DUMP    ⇔  direct url → dump\n"
    "⏹ /kill         ⇔  roko + jitna hua utna bhejo\n\n"
    "👇 pick from keyboard below"
)

HEADER_KW      = "🔑 *keywords* — pick a count from keyboard"
HEADER_DORK    = "🎯 *dorks* — pick a category"
HEADER_PARSE   = "🌐 *parser* — pick engine"
HEADER_SQLI    = "💉 *sqli* — pick mode"
HEADER_DUMP    = "📦 *dump* — pick action"
HEADER_VALIDATE = "📄 *validate* — tap below"
HEADER_DEDUPE  = "🧹 *dedupe* — tap below"
HEADER_OUTPUT  = "📤 *output* — pick format"
HEADER_AUTO    = "🚀 *auto* — pick input source"
HEADER_STATUS  = "📊 *status*"
HEADER_FETCH   = "📥 *fetch* — pick file"
HEADER_HELP    = "🛠 *help* — pick a topic"


# ─── screen registry ──────────────────────────────────────────────────
# maps a screen key -> (header_text, keyboard)
SCREENS = {
    "main":     (HEADER_MAIN,     MAIN),
    "kw":       (HEADER_KW,       KW),
    "dork":     (HEADER_DORK,     DORK),
    "parse":    (HEADER_PARSE,    PARSE),
    "sqli":     (HEADER_SQLI,     SQLI),
    "dump":     (HEADER_DUMP,     DUMP),
    "validate": (HEADER_VALIDATE, VALIDATE),
    "dedupe":   (HEADER_DEDUPE,   DEDUPE),
    "output":   (HEADER_OUTPUT,   OUTPUT),
    "auto":     (HEADER_AUTO,     AUTO),
    "status":   (HEADER_STATUS,   STATUS),
    "fetch":    (HEADER_FETCH,    FETCH),
    "help":     (HEADER_HELP,     HELP),
}


def get_screen(key):
    return SCREENS.get(key, SCREENS["main"])
