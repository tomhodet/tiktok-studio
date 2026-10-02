"""Brouillons de publication GitHub (releases en mode brouillon, visibles seulement par le propriétaire du
dépôt) : un brouillon par jour de contenu, qui reçoit les 5 vidéos du jour avec couvertures et légendes.

  python3 releases.py plan                     -> lignes « episodes=… » et « persos=… » pour $GITHUB_OUTPUT
  python3 releases.py envoyer <id_release> <fichier> [...]
Variables : GH_TOKEN (jeton du workflow), GITHUB_REPOSITORY (propriétaire/dépôt).
Commande : tiktok/commande.json {"lots": ["j002", "j003"] ou "j002-j030", "refaire": false}
"""
import json
import mimetypes
import os
import re
import sys
import urllib.request
from pathlib import Path

API = "https://api.github.com"
DEPOT = os.environ.get("GITHUB_REPOSITORY", "")


def appel(methode: str, url: str, donnees=None, entetes=None) -> dict | list | None:
    corps = None
    h = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28"}
    if isinstance(donnees, (bytes, bytearray)):
        corps = donnees
    elif donnees is not None:
        corps = json.dumps(donnees).encode()
        h["Content-Type"] = "application/json"
    h.update(entetes or {})
    req = urllib.request.Request(url if url.startswith("http") else API + url, data=corps, headers=h, method=methode)
    with urllib.request.urlopen(req, timeout=600) as r:
        texte = r.read()
    return json.loads(texte) if texte else None


def toutes_releases() -> list[dict]:
    res, page = [], 1
    while True:
        lot = appel("GET", f"/repos/{DEPOT}/releases?per_page=100&page={page}")
        res += lot
        if len(lot) < 100:
            return res
        page += 1


def lots_commandes() -> list[str]:
    c = json.loads(Path("tiktok/commande.json").read_text(encoding="utf-8"))
    lots = c["lots"]
    if isinstance(lots, str):           # « j002-j030 »
        a, b = (int(x) for x in re.findall(r"\d+", lots))
        lots = [f"j{k:03d}" for k in range(a, b + 1)]
    return [l for l in lots if Path(f"tiktok/lots/{l}.json").exists()]


def plan() -> None:
    commande = json.loads(Path("tiktok/commande.json").read_text(encoding="utf-8"))
    existantes = {r["tag_name"]: r for r in toutes_releases()}
    persos_json = json.loads(Path("tiktok/personnages.json").read_text(encoding="utf-8"))
    episodes, persos = [], set()
    for lot in lots_commandes():
        tag = f"jour-{lot[1:]}"
        rel = existantes.get(tag)
        if rel is None:
            rel = appel("POST", f"/repos/{DEPOT}/releases",
                        {"tag_name": tag, "name": f"Jour {int(lot[1:])}", "draft": True,
                         "body": "Les 5 vidéos du jour : vidéo, couverture, légende, rapport de vérification.\n"
                                 "Un nom en _A_VERIFIER signale une phrase que la vérification automatique a mal "
                                 "entendue : écouter avant de publier."})
        deja = {a["name"] for a in rel.get("assets", [])}
        for e in json.loads(Path(f"tiktok/lots/{lot}.json").read_text(encoding="utf-8"))["episodes"]:
            if not commande.get("refaire") and (f"{e['id']}.mp4" in deja or f"{e['id']}_A_VERIFIER.mp4" in deja):
                continue
            episodes.append({"ep": e["id"], "lot": lot, "perso": e["perso"], "release": rel["id"],
                             "fond": persos_json[e["perso"]]["fond"]["video"]})
            persos.add(e["perso"])
    episodes = episodes[:240]            # une exécution GitHub accepte 256 tâches au plus ; la suite au prochain envoi
    persos = {e["perso"] for e in episodes}
    print("episodes=" + json.dumps(episodes))
    print("persos=" + json.dumps(sorted(persos)))
    print(f"{len(episodes)} épisodes à fabriquer", file=sys.stderr)


def envoyer(rid: str, fichiers: list[str]) -> None:
    rel = appel("GET", f"/repos/{DEPOT}/releases/{rid}")
    for f in map(Path, fichiers):
        for a in rel.get("assets", []):
            if a["name"] == f.name:
                appel("DELETE", f"/repos/{DEPOT}/releases/assets/{a['id']}")
        type_ = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        url = rel["upload_url"].split("{")[0] + "?name=" + urllib.request.quote(f.name)
        appel("POST", url, f.read_bytes(), {"Content-Type": type_})
        print("envoyé", f.name, f"{f.stat().st_size // 1000} ko")


if __name__ == "__main__":
    if sys.argv[1] == "plan":
        plan()
    elif sys.argv[1] == "envoyer":
        envoyer(sys.argv[2], sys.argv[3:])
