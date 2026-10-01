# Studio de voix et de vérification

Génération des voix des épisodes (Chatterbox, licence MIT) et vérification finale par transcription
(Whisper), sur GitHub Actions.

- `tiktok/voix_cb.json` : liste des tâches de voix ; un envoi qui modifie ce fichier lance les calculs.
- `tiktok/<épisode>/script.json` : texte de chaque épisode.
- Les références de voix et toutes les prises sont **chiffrées** (`.enc`, AES-256). La clé est un secret
  du dépôt (`COFFRE_CLE`) ; aucun son en clair n'est jamais publié ici (`.gitignore`).
