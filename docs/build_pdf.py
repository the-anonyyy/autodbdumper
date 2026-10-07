#!/usr/bin/env python3
"""Build AutoDump-Noob-Guide.pdf — professional v2 layout.

Structure: cover -> contents -> intro -> Part 1..5 (each on fresh page w/ banner)
-> FAQ -> Appendix divider -> one page per source file.

Code blocks are copy-safe: real monospace, no line numbers, font auto-sized so
no line ever wraps (wrapping would inject newlines on copy-paste -> syntax errors).
Tables are rendered as clean cards (never cramped/overlapping).
"""
import os
import re
import markdown
from fpdf import FPDF

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "NOOB_GUIDE.md")
OUT = os.path.join(BASE, "AutoDump-Noob-Guide.pdf")

ACCENT = (30, 58, 138)        # deep blue
ACCENT_SOFT = (235, 240, 255)
CODE_BG = (244, 244, 244)
GRAY = (110, 110, 110)
DARK = (20, 20, 20)


class GuidePDF(FPDF):
    def footer(self):
        if self.page_no() <= 1:
            return
        self.set_y(-14)
        self.set_font("body", "I", 8)
        self.set_text_color(*GRAY)
        self.cell(0, 8, f"Auto Dump — Noob Guide    |    Page {self.page_no()}/{{nb}}",
                  align="C")


pdf = GuidePDF(format="A4")
pdf.alias_nb_pages("{nb}")
pdf.set_auto_page_break(True, margin=18)
pdf.set_margins(16, 14, 16)
pdf.set_title("Auto Dump — Noob Guide")
pdf.set_author("Auto Dump")
pdf.set_subject("Telegram bot: setup, usage, full source code")

# Unicode fonts: Noto Sans (body) + DejaVu Sans Mono (code, has ─ █ ░ etc.)
_FD = "/usr/share/fonts/truetype"
pdf.add_font("body", "", f"{_FD}/noto/NotoSans-Regular.ttf")
pdf.add_font("body", "B", f"{_FD}/noto/NotoSans-Bold.ttf")
pdf.add_font("body", "I", f"{_FD}/noto/NotoSans-Italic.ttf")
pdf.add_font("codemono", "", f"{_FD}/dejavu/DejaVuSansMono.ttf")
pdf.add_font("codemono", "B", f"{_FD}/dejavu/DejaVuSansMono-Bold.ttf")

# Emoji -> readable text (PDF fonts have no color-emoji glyphs; tofu boxes
# would look broken AND copy badly). Chat-message emoji become [text].
EMOJI_MAP = {
    "⏹": "[STOP]", "⚙": "[setup]", "⚠": "[!]", "⚡": "[fast]", "✅": "[OK]",
    "✏": "[edit]", "❌": "[X]", "⬅": "[<]", "⬇": "[v]", "🌍": "[web]",
    "🌐": "[net]", "🌟": "[*]", "🎭": "[mask]", "🎯": "[target]", "🏗": "[build]",
    "👇": "[v]", "💉": "[sqli]", "📁": "[dir]", "📂": "[dir]", "📄": "[file]",
    "📈": "[chart]", "📊": "[stats]", "📋": "[list]", "📎": "[file]",
    "📤": "[out]", "📥": "[in]", "📦": "[box]", "🔄": "[reload]", "🔑": "[key]",
    "🔗": "[link]", "🔵": "[*]", "🕵": "[scan]", "🗂": "[files]", "🙂": ":)",
    "🚀": "[go]", "🛠": "[tool]", "🥇": "[1st]", "🥈": "[2nd]", "🥉": "[3rd]",
    "🦆": "[duck]", "🧩": "[part]", "🧹": "[clean]", "🧾": "[bill]",
    "🪱": "[worm]", "️": "",
    "→": "->",  # NotoSans lacks U+2192; DejaVu Mono has it but keep body clean
}


def sanitize(s):
    return "".join(EMOJI_MAP.get(c, c) for c in s)

USABLE_W = 210 - 16 - 16  # 178 mm


def rule():
    pdf.ln(3)
    y = pdf.get_y()
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.6)
    pdf.line(16, y, 194, y)
    pdf.ln(5)


def h3(text):
    pdf.ln(4)
    if pdf.get_y() > 255:
        pdf.add_page()
    pdf.set_font("body", "B", 12)
    pdf.set_text_color(*ACCENT)
    pdf.multi_cell(0, 7, sanitize(text))
    pdf.set_text_color(*DARK)
    pdf.ln(1)


def body_html(html):
    pdf.set_font("body", "", 10.5)
    pdf.set_text_color(*DARK)
    pdf.write_html(sanitize(html), table_line_separators=True)
    pdf.ln(2)


def render_quote(lines):
    text = sanitize(" ".join(l.lstrip(">").strip() for l in lines))
    html = markdown.markdown(text)
    y0 = pdf.get_y()
    pdf.set_x(22)
    pdf.set_font("body", "I", 10.5)
    pdf.set_text_color(70, 70, 70)
    pdf.write_html(f"<i>{html}</i>")
    y1 = pdf.get_y()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(16, y0 + 1, 2.5, max(4, y1 - y0 - 2), style="F")
    pdf.set_text_color(*DARK)
    pdf.ln(3)


def render_code(lines, lang=""):
    """Copy-safe: monospace, no wrap (auto-shrink), one text line per code line."""
    lines = [sanitize(l.rstrip().replace("\t", "    ")) for l in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return
    longest = max(lines, key=len)
    # fit: measure the longest line, scale so it fits without wrapping
    pdf.set_font("codemono", "", 7.5)
    w = pdf.get_string_width(longest) or 1
    size = 7.5 * (USABLE_W - 8) / w
    size = max(5.5, min(7.5, size))
    lh = size * 0.52

    pdf.ln(2)
    if pdf.get_y() + lh * 3 > pdf.page_break_trigger:
        pdf.add_page()
    if lang:
        pdf.set_font("body", "B", 8)
        pdf.set_text_color(*GRAY)
        pdf.cell(0, 5, sanitize(lang), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*DARK)

    pdf.set_font("codemono", "", size)
    for line in lines:
        if pdf.get_y() + lh > pdf.page_break_trigger:
            pdf.add_page()
        y = pdf.get_y()
        pdf.set_fill_color(*CODE_BG)
        pdf.rect(16, y, USABLE_W, lh, style="F")
        pdf.set_xy(18, y)
        # text never wraps because size was fitted to the longest line
        pdf.multi_cell(USABLE_W - 4, lh, line if line else " ")
    pdf.ln(2)
    pdf.set_font("body", "", 10.5)


def render_table_cards(rows):
    """rows: [header, sep, r1, r2, ...] -> clean vertical cards."""
    if len(rows) < 3:
        return
    header = [c.strip() for c in rows[0]]
    for r in rows[2:]:
        cells = [c.strip() for c in r]
        if not any(cells):
            continue
        if pdf.get_y() > 240:
            pdf.add_page()
        pdf.ln(2)
        # card title from first column (+ second col appended for context)
        title = cells[0]
        if (len(cells) > 1 and cells[1] and len(header) > 1
                and header[0].lower() in ("step", "#", "s.no")):
            title = f"{cells[0]} — {cells[1]}"
            rest = list(zip(header[2:], cells[2:]))
        else:
            rest = list(zip(header[1:], cells[1:]))
        y0 = pdf.get_y()
        pdf.set_font("body", "B", 10.5)
        pdf.set_text_color(*ACCENT)
        pdf.multi_cell(0, 6, sanitize(title))
        pdf.set_text_color(*DARK)
        for h, c in rest:
            if not c:
                continue
            pdf.set_font("body", "", 10)
            body_html(f"<b>{sanitize(h)}:</b> {sanitize(c)}")
        y1 = pdf.get_y()
        pdf.set_fill_color(*ACCENT)
        pdf.rect(16, y0, 2, y1 - y0, style="F")


def section_banner(kicker, title, subtitle=""):
    pdf.add_page()
    pdf.start_section(sanitize(f"{kicker} — {title}"), level=0)
    pdf.ln(14)
    y = pdf.get_y()
    pdf.set_fill_color(*ACCENT)
    pdf.rect(16, y, USABLE_W, 26, style="F")
    pdf.set_xy(21, y + 3)
    pdf.set_font("body", "B", 10)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 6, sanitize(kicker), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(21)
    pdf.set_font("body", "B", 16)
    pdf.multi_cell(USABLE_W - 10, 8, sanitize(title))
    pdf.set_y(y + 30)
    if subtitle:
        pdf.set_font("body", "I", 10.5)
        pdf.set_text_color(*GRAY)
        pdf.multi_cell(0, 6, sanitize(subtitle))
        pdf.set_text_color(*DARK)
    pdf.ln(4)


# ---------------------------------------------------------------- parsing
raw = open(SRC, encoding="utf-8").read().splitlines()

# split into sections on '## ' headings
sections = []          # (kind, kicker, title, lines)
cur = None
preamble = []
for line in raw:
    m = re.match(r"^##\s+(.*)", line)
    if m:
        if cur:
            sections.append(cur)
        head = m.group(1).strip()
        pm = re.match(r"Part\s+(\d+)\s+[—–-]\s*(.*)", head)
        am = re.match(r"Appendix\s+A\s+[—–-]\s*(.*)", head, re.I)
        if pm:
            cur = ("part", f"PART {pm.group(1)}", pm.group(2).strip(), [])
        elif am:
            cur = ("appendix", "APPENDIX A", am.group(1).strip(), [])
        else:
            cur = ("faq", "FAQ", head, [])
    else:
        if cur is None:
            if line.strip() and not line.startswith("# "):
                preamble.append(line)
        else:
            cur[3].append(line)
if cur:
    sections.append(cur)

SUBTITLES = {
    "PART 1": "Poora system ek nazar mein — kya hota hai, kis order mein",
    "PART 2": "Har file ka kaam, ek line mein",
    "PART 3": "Server ready karo — shuru se aakhir tak",
    "PART 4": "Telegram pe bot kaise chalate hain, step by step",
    "PART 5": "Kuch gadbad ho to yahan dekho",
    "FAQ": "Aksar puche jaane wale sawaal",
}


def render_section_body(lines, appendix=False):
    """State machine: text / lists / quotes / tables / code / h3."""
    if appendix:
        render_appendix(lines)
        return
    buf, table, quote = [], [], []
    code, fence_lang = None, ""
    fences = ("```", "~~~")

    def flush_text():
        if buf:
            body_html(markdown.markdown("\n".join(buf)))
            buf.clear()

    def flush_table():
        if table:
            rows = [[c.strip() for c in re.split(r"(?<!\\)\|", l.strip().strip("|"))]
                    for l in table]
            render_table_cards(rows)
            table.clear()

    def flush_quote():
        if quote:
            render_quote(quote)
            quote.clear()

    for line in lines + [""]:
        s = line.strip()
        if code is not None:
            if s.startswith(fences):
                render_code(code, fence_lang)
                code, fence_lang = None, ""
            else:
                code.append(line.rstrip("\n"))
            continue
        if s.startswith(fences):
            flush_text(); flush_table(); flush_quote()
            fence_lang = s.strip("`~").strip()
            code = []
            continue
        if re.match(r"^###\s+", s):
            flush_text(); flush_table(); flush_quote()
            h3(re.sub(r"^###\s+", "", s).replace("`", ""))
            continue
        if s.startswith("|") and s.endswith("|"):
            flush_text(); flush_quote()
            table.append(line)
            continue
        if s.startswith(">"):
            flush_text(); flush_table()
            quote.append(line)
            continue
        if re.match(r"^---+\s*$", s):
            flush_text(); flush_table(); flush_quote()
            rule()
            continue
        if not s:
            flush_text(); flush_table(); flush_quote()
            pdf.ln(1)
            continue
        if table and not s.startswith("|"):
            flush_table()
        if quote and not s.startswith(">"):
            flush_quote()
        buf.append(line)
    flush_text(); flush_table(); flush_quote()


def render_appendix(lines):
    # intro text before first '### `file`'
    intro, rest = [], []
    seen_file = False
    for line in lines:
        if re.match(r"^###\s+`", line.strip()):
            seen_file = True
        (rest if seen_file else intro).append(line)
    if intro:
        render_section_body(intro)

    # copy-tip box
    pdf.ln(2)
    y0 = pdf.get_y()
    pdf.set_fill_color(*ACCENT_SOFT)
    pdf.set_font("body", "B", 10.5)
    pdf.set_text_color(*ACCENT)
    tip = sanitize("COPY TIP — code bilkul copy-safe hai: monospace font, koi line number "
                      "nahi, koi line wrap nahi. Select karo, copy karo, file mein paste karo — "
                      "paste ke baad error nahi aayega. (Chat wali emoji PDF mein [text] "
                      "bankar dikhengi — sirf dikhne ke liye hain.)")
    pdf.set_x(20)
    pdf.multi_cell(USABLE_W - 8, 6, tip)
    y1 = pdf.get_y()
    pdf.rect(16, y0 - 2, USABLE_W, y1 - y0 + 4, style="D")
    pdf.set_text_color(*DARK)
    pdf.ln(4)

    fname, code, fence = None, None, ""
    for line in rest + [""]:
        s = line.strip()
        m = re.match(r"^###\s+`([^`]+)`", s)
        if m:
            fname = m.group(1)
            pdf.add_page()
            pdf.start_section(fname, level=1)
            y = pdf.get_y()
            pdf.set_fill_color(*DARK)
            pdf.rect(16, y, USABLE_W, 12, style="F")
            pdf.set_xy(20, y + 2)
            pdf.set_font("codemono", "B", 11)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(0, 8, fname)
            pdf.set_text_color(*DARK)
            pdf.set_y(y + 16)
            code = None
            continue
        if code is not None:
            if s.startswith(("```", "~~~")):
                render_code(code, fence)
                code = None
            else:
                code.append(line.rstrip("\n"))
            continue
        if s.startswith(("```", "~~~")):
            fence = s.strip("`~").strip()
            code = []
            continue
    pdf.set_font("body", "", 10.5)


# ---------------------------------------------------------------- build
# COVER
pdf.add_page()
pdf.ln(42)
pdf.set_font("body", "B", 44)
pdf.set_text_color(*ACCENT)
pdf.cell(0, 20, "Auto Dump", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.set_font("body", "", 22)
pdf.set_text_color(*DARK)
pdf.cell(0, 14, "Noob Guide", align="C", new_x="LMARGIN", new_y="NEXT")
pdf.ln(4)
y = pdf.get_y()
pdf.set_draw_color(*ACCENT)
pdf.set_line_width(1)
pdf.line(80, y, 130, y)
pdf.ln(8)
pdf.set_font("body", "", 12)
pdf.set_text_color(*GRAY)
pdf.multi_cell(0, 7, "Telegram bot — dorks se URLs, SQLi scan,\n"
                     "dump, validate, dedupe — file in, file out.",
               align="C")
pdf.ln(14)
pdf.set_font("body", "", 10.5)
pdf.set_text_color(*DARK)
pdf.cell(0, 7, "Version 1.0  •  October 2026", align="C",
         new_x="LMARGIN", new_y="NEXT")
pdf.set_font("body", "I", 10)
pdf.set_text_color(*GRAY)
pdf.cell(0, 7, "Zero se setup, Telegram pe usage, poora source code",
         align="C", new_x="LMARGIN", new_y="NEXT")

# CONTENTS
pdf.add_page()
pdf.start_section("Contents", level=0)
pdf.set_font("body", "B", 18)
pdf.set_text_color(*ACCENT)
pdf.cell(0, 12, "Contents", new_x="LMARGIN", new_y="NEXT")
rule()
toc = [
    ("Introduction", "How to use this guide"),
    ("Part 1 — Blueprint", "What is this project? The full system at a glance"),
    ("Part 2 — Code Map", "What each file does"),
    ("Part 3 — Setup Guide", "Get the server ready, from zero"),
    ("Part 4 — Usage Guide", "How to operate the bot on Telegram"),
    ("Part 5 — Troubleshooting", "What to do when something breaks"),
    ("FAQ", "Frequently asked questions"),
    ("Appendix A — Source Code", "Complete code in copy-safe format"),
]
pdf.set_font("body", "", 11)
pdf.set_text_color(*DARK)
for i, (t, d) in enumerate(toc, 1):
    pdf.set_font("body", "B", 11)
    pdf.set_text_color(*ACCENT)
    pdf.cell(12, 8, f"{i}.")
    pdf.set_text_color(*DARK)
    pdf.cell(0, 8, t, new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(28)
    pdf.set_font("body", "", 10)
    pdf.set_text_color(*GRAY)
    pdf.cell(0, 6, d, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*DARK)
    pdf.ln(2)

# INTRODUCTION (preamble)
section_banner("BEFORE YOU BEGIN", "Introduction",
               "How to use this guide — understand in 2 minutes")
render_section_body(preamble)

# PARTS / FAQ / APPENDIX
for kind, kicker, title, lines in sections:
    if kind == "part":
        section_banner(kicker, title, SUBTITLES.get(kicker, ""))
    elif kind == "faq":
        section_banner("FAQ", title, SUBTITLES.get("FAQ", ""))
    else:
        section_banner("APPENDIX A", title,
                       "Har file poori ki poori — copy-paste ready")
    render_section_body(lines, appendix=(kind == "appendix"))

pdf.output(OUT)
print("wrote", OUT, os.path.getsize(OUT), "bytes")
