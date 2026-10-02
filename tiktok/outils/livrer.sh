#!/usr/bin/env bash
# Livraison d'un épisode vérifié : compression en deux passes (moins de 30 Mo), couverture, légende.
#   bash tiktok/outils/livrer.sh tiktok/j001_grandmere /home/claude/livraison/j001
set -euo pipefail
EP="$1"; DEST="$2"
cd "$(dirname "$0")/../.."
NOM=$(basename "$EP")
mkdir -p "$DEST"
TMP=$(mktemp -d)
ffmpeg -v error -y -i "$EP/${NOM}_finale.mp4" -c:v libx264 -b:v 3200k -preset slow -pass 1 -passlogfile "$TMP/p" -an -f null /dev/null
ffmpeg -v error -y -i "$EP/${NOM}_finale.mp4" -c:v libx264 -b:v 3200k -preset slow -pass 2 -passlogfile "$TMP/p" \
  -pix_fmt yuv420p -c:a aac -b:a 160k -movflags +faststart "$DEST/${NOM}.mp4"
rm -rf "$TMP"
python3 tiktok/outils/couverture.py "$EP" "$DEST/${NOM}_couverture.jpg" > /dev/null
python3 -c "import json; s=json.load(open('$EP/script.json')); print(s.get('legende',''))" > "$DEST/${NOM}_legende.txt"
echo "livré $DEST/${NOM}.mp4 ($(du -m "$DEST/${NOM}.mp4" | cut -f1) Mo)"
