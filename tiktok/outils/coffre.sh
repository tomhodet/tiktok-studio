#!/usr/bin/env bash
# Coffre : chiffre ou déchiffre les fichiers audio du dépôt public (AES-256, clé dans le secret COFFRE_CLE).
#   coffre.sh chiffrer   <dossier>   : chaque .wav/.flac du dossier (récursif) -> .enc à côté, l'original reste
#   coffre.sh dechiffrer <dossier>   : chaque .enc -> fichier en clair à côté (ignoré par git)
set -euo pipefail
[ -n "${COFFRE_CLE:-}" ] || { echo "COFFRE_CLE manquante" >&2; exit 1; }
mode="$1"; dossier="$2"
if [ "$mode" = chiffrer ]; then
  find "$dossier" -type f \( -name '*.wav' -o -name '*.flac' \) | while read -r f; do
    [ -f "$f.enc" ] && [ "$f.enc" -nt "$f" ] && continue
    openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in "$f" -out "$f.enc" -pass env:COFFRE_CLE
  done
elif [ "$mode" = dechiffrer ]; then
  find "$dossier" -type f -name '*.enc' | while read -r f; do
    [ -f "${f%.enc}" ] && continue
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in "$f" -out "${f%.enc}" -pass env:COFFRE_CLE
  done
else
  echo "usage : coffre.sh chiffrer|dechiffrer <dossier>" >&2; exit 2
fi
