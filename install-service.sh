#!/bin/bash
# install / reinstall the autocc-bot systemd service
set -e
UNIT_SRC="/home/hatch/workspace/autocc/autocc-bot.service"
UNIT_DST="/etc/systemd/system/autocc-bot.service"
cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable autocc-bot.service
systemctl restart autocc-bot.service
echo "autocc-bot installed and started"
systemctl is-active autocc-bot.service
