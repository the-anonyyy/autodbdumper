# AUTOCC — Autodump Command Center

Telegram bot + pipeline for authorized security-testing workflows:
dork generation, URL parsing, live-host prefilter, sqlmap scanning
(CLI + REST API mode), dump enumeration, validation, dedupe,
and multi-format output.

> ⚠️ **Use only on targets you own or are explicitly authorized to test.**
> The authors are not responsible for misuse.

## Install

```bash
git clone <your-repo> autocc
cd autocc
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# external tools
go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@latest
go install github.com/projectdiscovery/httpx/cmd/httpx@latest
go install github.com/projectdiscovery/katana/cmd/katana@latest
```

Make sure `$GOPATH/bin` is on your `PATH`. sqlmap lives at
`~/workspace/sqlmap` (see `install-service.sh` / `modules/sqli.py`).

## Configure

```bash
cp config.example.yaml config.yaml
```

Edit `config.yaml`:

- `telegram.token` — from @BotFather
- `telegram.allowed_chat_ids` — your chat id(s)
- `dump.target_db` — database name to target

(`config.yaml` is git-ignored — secrets kabhi commit mat karo.)

## Run — Telegram bot (reply-keyboard UI)

```bash
python -u bot.py
```

Har stage file-in → file-out hai: bot file maangta hai (ya pasted text
bhi chalega), kaam karta hai, output file wapas bhejta hai.
Chat progress/output stream hai. `/kill` beech mein rok ke partial
results bhejta hai.

## Run — CLI (single stage)

```bash
python main.py --stage sqli -f data/raw/targets.txt
```

## Pipeline stages

1. **keywords/dorks** — 9 dork packs (generic, sqli, files, cms, country,
   hq_error, exposed, ecom, admin) + 35 country / 16 CMS templates
2. **parse** — 4 engines (DDGS, Bing, Brave, Mojeek), max 20 URLs/domain
3. **livecheck** — dead hosts prefilter (50 workers, 8s timeout)
4. **sqli** — sqlmap scan → `injectable.txt`
   (REST API mode + resume checkpoint: `/kill` ya restart ke baad wahi
   file dobara bhejo — scan wahi se continue hota hai)
5. **dump** — list DBs / list tables / full dump (4 parallel workers)
6. **validate** — Luhn + BIN → `validated.csv`
7. **dedupe** — unique + BIN report → `final.csv`
8. **output** — .txt / .csv / .json + auto `bundle.zip`

Extras: proxy rotation (HTTP/HTTPS/SOCKS4/SOCKS5) with live testing,
leaked-secrets scanner (redacted `secrets_found.json` report).

## Service (systemd)

```bash
sudo ./install-service.sh
systemctl status autocc-bot
```

15-min watchdog (`cron.d/minutely/autocc-bot-watchdog`) reinstalls +
restarts the service after VM replacements.

## Layout

```
autocc/
├── main.py  bot.py  config.yaml  config.example.yaml
├── modules/          # pipeline stages + helpers
├── docs/             # NOOB_GUIDE.md + PDF
├── data/             # runtime (git-ignored): raw/ dumps/ final/
└── logs/             # runtime (git-ignored)
```

## Docs

- `docs/NOOB_GUIDE.md` — poori noob guide
- `docs/AUTOCC-Noob-Guide.pdf` — 56-page PDF version
