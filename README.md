# Studio : fabrication des vidéos en série

Chaque vidéo est fabriquée de bout en bout sur GitHub Actions : prises de voix (Chatterbox, licence MIT),
tri des prises, reprises, montage, vérification de ce que le spectateur entend (Whisper), compression,
couverture et légende. Le résultat est déposé dans un **brouillon de publication** (release en brouillon),
un brouillon par jour de contenu, visible seulement par le propriétaire du dépôt.

- `tiktok/lots/jNNN.json` : les 5 histoires d'un jour (grand-mère, grand-père, père, mère, fou).
- `tiktok/commande.json` : `{"lots": ["j002", "j003"]}` ou `{"lots": "j002-j030"}`. Un envoi qui modifie ce
  fichier lance la fabrication (`.github/workflows/production.yml`). Les épisodes déjà livrés sont sautés.
- `tiktok/personnages.json` : voix, réglages, fond et couverture de chaque personnage.
- Les références de voix et les fonds vidéo sont **chiffrés** (`.enc`, AES-256, clé dans le secret
  `COFFRE_CLE`). Aucun son ni aucune vidéo en clair n'est publié ici (`.gitignore`). Les prises de voix
  restent sur la machine de calcul.
- Un nom de fichier en `_A_VERIFIER` signale une phrase que la vérification automatique a mal entendue :
  à écouter avant de publier.
