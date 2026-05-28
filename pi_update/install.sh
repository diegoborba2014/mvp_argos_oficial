#!/bin/bash
# ARGOS Pi — Script de atualização remota
# Uso: bash <(curl -fsSL https://raw.githubusercontent.com/diegoborba2014/mvp_argos_oficial/master/pi_update/install.sh)

set -e
BASE="https://raw.githubusercontent.com/diegoborba2014/mvp_argos_oficial/master/pi_update"
DEST=~/argos/src

echo "[ARGOS UPDATE] Baixando arquivos atualizados..."

curl -fsSL "$BASE/main.py"          -o "$DEST/main.py"
curl -fsSL "$BASE/hotlist_sync.py"  -o "$DEST/hotlist_sync.py"
curl -fsSL "$BASE/config_polling.py" -o "$DEST/config_polling.py"
curl -fsSL "$BASE/webhook_handler.py" -o "$DEST/webhook_handler.py"
curl -fsSL "$BASE/offline_buffer.py" -o "$DEST/offline_buffer.py"

echo "[ARGOS UPDATE] Arquivos atualizados. Reiniciando serviço..."
sudo systemctl restart argos

echo "[ARGOS UPDATE] Concluído. Verifique com: sudo journalctl -u argos -n 30"
