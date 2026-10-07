# AUTOCC — Autodump Command Center

A Telegram-driven pipeline for **authorized security testing**: dork generation,
URL parsing, live-host prefiltering, SQL injection scanning (sqlmap CLI +
REST API), dump enumeration, validation, deduplication, and multi-format reporting.

> ⚠️ **Authorized targets only.** Use this tool exclusively on systems you own
> or have explicit written permission to test. Unauthorized scanning or
> exploitation is illegal in most jurisdictions. The authors accept no
> responsibility for misuse.

## Features

- **File-driven pipeline** — every stage takes a file (or pasted text) in and
  returns an output file; the chat is the progress/output stream
- **9 dork packs** + 35 country and 16 CMS templates
- **4 search engines** (DDGS, Bing, Brave, Mojeek) with per-domain caps
- **sqlmap REST API mode** with live per-target progress, ETA, and current-target display
- **Resume checkpoints** — after `/kill` or a server restart, resend the same
  targets file and the scan continues where it stopped
- **Live-host prefilter** — dead hosts are removed before scanning
- **Proxy rotation** (HTTP/HTTPS/SOCKS4/SOCKS5) with live proxy testing
- **4 parallel dump workers**, automatic `bundle.zip` export
- **Leaked-secrets scanner** (redacted report)

## Requirements

- Python 3.10+
- `sqlmap`
- `subfinder`, `httpx`, `katana` (ProjectDiscovery tools, installed via Go)
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

## Installation

**Step 1 — Clone the repository**

```bash
git clone https://github.com/the-anonyyy/autodbdumper.git
cd autodbdumper
```

**Step 2 — Create a virtual environment**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Step 3 — Install Python dependencies**

```bash
pip install -r requirements.txt
```

**Step 4 — Install external tools**

```bash
go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install github.com/projectdiscovery/httpx/cmd/httpx@latest
go install github.com/projectdiscovery/katana/cmd/katana@latest
```

Make sure `$GOPATH/bin` is on your `PATH`.

**Step 5 — Configure**

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml` and set:

- `telegram.token` — your bot token from @BotFather
- `telegram.allowed_chat_ids` — your Telegram chat ID(s)

> `config.yaml` is git-ignored. Never commit real tokens.

**Step 6 — Run the bot**

```bash
python -u bot.py
```

Open Telegram, find your bot, and press **Start**. All controls are
reply-keyboard buttons — no commands to memorize.

## Usage — Telegram bot

Each stage asks for its input file (you can also paste text directly),
does the work, and sends the output file back:

`keywords → dorks → parse → livecheck → sqli → dump → validate → dedupe → output`

- **`/kill`** — stop the running stage at any time; partial results are sent
- **Status screen** — shows every pipeline file with line counts and sizes,
  plus the resume checkpoint state

## Usage — CLI (single stage)

```bash
python main.py --stage sqli -f data/raw/targets.txt
```

Available stages: `keywords`, `dorks`, `parse`, `livecheck`, `sqli`,
`dump`, `validate`, `dedupe`, `output`.

## Pipeline stages

| # | Stage | Input → Output |
|---|-------|----------------|
| 1 | Keywords / Dorks | seed keyword → `dorks_*.txt` |
| 2 | Parse | dorks → `urls.txt`, `targets.txt` |
| 3 | Livecheck | targets → `targets_live.txt` |
| 4 | SQLi scan | targets → `injectable.txt` |
| 5 | Dump | injectables → `dbs.txt` / `tables.txt` / dumps |
| 6 | Validate | parsed data → `validated.csv` |
| 7 | Dedupe | validated → `final.csv` + BIN report |
| 8 | Output | final → `.txt` / `.csv` / `.json` + `bundle.zip` |

## Resume after interruption

SQLi scan progress is checkpointed to disk as it runs. If the scan is
stopped with `/kill` or the server restarts, simply resend the **same**
targets file — the scan resumes where it left off instead of starting over.
Delete `.sqli_checkpoint.json` (via Status → Remove Files) to force a fresh scan.

## Running as a service (systemd)

```bash
sudo ./install-service.sh
systemctl status autocc-bot
```

A 15-minute watchdog reinstalls and restarts the service automatically
after VM replacements.

## Project layout

```
autodbdumper/
├── main.py  bot.py  config.yaml  config.example.yaml
├── modules/            # pipeline stages + helpers
├── docs/               # NOOB_GUIDE.md + PDF guide
├── data/               # runtime files (git-ignored): raw/ dumps/ final/
└── logs/               # runtime logs (git-ignored)
```

## Documentation

- [`docs/NOOB_GUIDE.md`](docs/NOOB_GUIDE.md) — complete beginner's guide
- [`docs/AUTOCC-Noob-Guide.pdf`](docs/AUTOCC-Noob-Guide.pdf) — 56-page PDF version

## License

MIT — see [LICENSE](LICENSE). The security notice in the license applies:
authorized testing only.
