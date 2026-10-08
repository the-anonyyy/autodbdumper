# Auto Dump

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

Downloads the project source code to your machine:

```bash
git clone https://github.com/the-anonyyy/autodbdumper.git
```

```bash
cd autodbdumper
```

`git clone` copies the repo; `cd` moves you into the project folder —
every command below runs from here.

**Step 2 — Create a virtual environment**

Isolates the project's Python packages from your system Python so nothing
conflicts:

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

The first command creates the environment folder `.venv`; the second
activates it (your terminal prompt will show `(.venv)`).

**Step 3 — Install Python dependencies**

Installs everything the bot needs (Telegram library, YAML parser,
HTTP client, etc.):

```bash
pip install -r requirements.txt
```

**Step 4 — Install external recon tools**

These are the binaries the recon stage shells out to:

```bash
go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
```

Subdomain enumeration — finds subdomains of a target domain.

```bash
go install github.com/projectdiscovery/httpx/cmd/httpx@latest
```

Live-host probing — checks which hosts/URLs actually respond.

```bash
go install github.com/projectdiscovery/katana/cmd/katana@latest
```

URL crawler — extracts links and parameters from pages.

Then make sure Go's binary folder is on your `PATH`, otherwise the
pipeline won't find these tools:

```bash
export PATH="$PATH:$(go env GOPATH)/bin"
```

**Step 5 — Configure**

Create your personal config file from the template:

```bash
cp config.example.yaml config.yaml
```

This copies the placeholder template into `config.yaml`, which is
git-ignored — it stays on your machine and is never uploaded.

### 🔑 Bot token — you MUST replace this

The bot cannot connect to Telegram without a real token. Do this now:

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
   Send `/newbot` and follow the prompts (name + username ending in `bot`).
   BotFather replies with a token like `123456789:AAE...`.
2. Open `config.yaml` and **replace the placeholder values**:

```yaml
telegram:
  token: "YOUR_BOT_TOKEN_HERE"          # ← paste your BotFather token here
  allowed_chat_ids: ["YOUR_CHAT_ID_HERE"]  # ← your numeric Telegram chat ID
```

3. To find your chat ID, message [@userinfobot](https://t.me/userinfobot)
   on Telegram — it replies with your numeric ID. Only these chat IDs are
   allowed to control the bot.

> ⚠️ Nothing works until you replace the token — the bot cannot reach
> Telegram with the placeholder. Never share your token, and never commit
> `config.yaml` (it's git-ignored for exactly this reason).

**Step 6 — Run the bot**

Starts the Telegram bot in the foreground:

```bash
python -u bot.py
```

(`-u` means unbuffered output, so log lines appear immediately instead
of being buffered.)

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

Runs one pipeline stage directly, without the Telegram bot:

```bash
python main.py --stage sqli -f data/raw/targets.txt
```

- `--stage sqli` — which stage to run (see list below)
- `-f data/raw/targets.txt` — the input file for that stage

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

Installs the bot as a system service so it runs 24/7 and survives reboots:

```bash
sudo ./install-service.sh
```

(Copies the unit file, enables it, and starts it.)

Check that it's running:

```bash
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
- [`docs/AutoDump-Noob-Guide.pdf`](docs/AutoDump-Noob-Guide.pdf) — 56-page PDF version

## License

MIT — see [LICENSE](LICENSE). The security notice in the license applies:
authorized testing only.
