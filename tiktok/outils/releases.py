"""Brouillons de publication GitHub (releases en mode brouillon, visibles seulement par le propriétaire du
dépôt) : un brouillon par jour de contenu, qui reçoit les 5 vidéos du jour avec couvertures et légendes.

  python3 releases.py plan                     -> lignes « episodes=… » et « persos=… » pour $GITHUB_OUTPUT
  python3 releases.py envoyer <id_release> <fichier> [...]
  python3 releases.py echec <id_release> <lot> <episode>   consigne un échec (voix incomplète, montage raté)
Rattrapage : chaque exécution reprend d'abord les épisodes des jours précédents restés sans vidéo, sauf ceux
déjà en échec avec le même texte et les mêmes règles de voix (fichier <épisode>_ECHEC_<empreinte>.txt).
Variables : GH_TOKEN (jeton du workflow), GITHUB_REPOSITORY (propriétaire/dépôt).
Commande : tiktok/commande.json {"lots": ["j002", "j003"] ou "j002-j030", "refaire": false}
"""
import hashlib
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
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
    texte = reessayer(lambda: urllib.request.urlopen(req, timeout=600))
    return json.loads(texte) if texte else None


def reessayer(ouvrir, essais: int = 5) -> bytes:
    """GitHub répond parfois 500 ou 502 quelques secondes : on réessaie au lieu d'échouer."""
    for k in range(essais):
        try:
            with ouvrir() as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 or k == essais - 1:
                raise
        except urllib.error.URLError:
            if k == essais - 1:
                raise
        time.sleep(5 * (k + 1))


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
    lots = os.environ.get("LOTS") or c["lots"]      # LOTS : lancement enchaîné (workflow_dispatch)
    if isinstance(lots, str):           # « j002-j030 »
        a, b = (int(x) for x in re.findall(r"\d+", lots))
        lots = [f"j{k:03d}" for k in range(a, b + 1)]
    return [l for l in lots if Path(f"tiktok/lots/{l}.json").exists()]


def empreinte(e: dict) -> str:
    """Texte de l'épisode et règles de voix : un échec n'est retenté que si l'un des deux a changé."""
    h = hashlib.sha1(json.dumps(e["phrases"], ensure_ascii=False).encode())
    for f in ("choisir_voix.py", "verif_voix.py", "texte_oral.py"):
        h.update((Path(__file__).parent / f).read_bytes())
    return h.hexdigest()[:10]


def livree(e: dict, deja: set) -> bool:
    return f"{e['id']}.mp4" in deja or f"{e['id']}_A_VERIFIER.mp4" in deja


def rattrapage(existantes: dict, premier: int, persos_json: dict) -> list[dict]:
    """Épisodes des jours déjà commandés restés sans vidéo (échec, interruption) : repris en tête."""
    res = []
    for k in range(1, premier):
        rel, f = existantes.get(f"jour-{k:03d}"), Path(f"tiktok/lots/j{k:03d}.json")
        if rel is None or not f.exists():
            continue
        deja = {a["name"] for a in rel.get("assets", [])}
        for e in json.loads(f.read_text(encoding="utf-8"))["episodes"]:
            if livree(e, deja) or f"{e['id']}_ECHEC_{empreinte(e)}.txt" in deja:
                continue
            res.append({"ep": e["id"], "lot": f.stem, "perso": e["perso"], "release": rel["id"],
                        "fond": persos_json[e["perso"]]["fond"]["video"]})
    if res:
        print(f"rattrapage : {[x['ep'] for x in res]}", file=sys.stderr)
    return res


def plan() -> None:
    commande = json.loads(Path("tiktok/commande.json").read_text(encoding="utf-8"))
    existantes = {r["tag_name"]: r for r in toutes_releases()}
    persos_json = json.loads(Path("tiktok/personnages.json").read_text(encoding="utf-8"))
    lots = lots_commandes()
    episodes = rattrapage(existantes, int(lots[0][1:]), persos_json) if lots else []
    for lot in lots:
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
            if not commande.get("refaire") and livree(e, deja):
                continue
            episodes.append({"ep": e["id"], "lot": lot, "perso": e["perso"], "release": rel["id"],
                             "fond": persos_json[e["perso"]]["fond"]["video"]})
    episodes = episodes[:250]            # 256 tâches au plus par exécution ; le reste est rattrapé à l'exécution suivante
    persos = {e["perso"] for e in episodes}
    print("episodes=" + json.dumps(episodes))
    print("persos=" + json.dumps(sorted(persos)))
    dernier = max(int(l[1:]) for l in lots) if lots else 0
    print(f"suite=j{dernier + 1:03d}-j{min(dernier + 48, 999):03d}" if Path(f"tiktok/lots/j{dernier + 1:03d}.json").exists()
          else "suite=")
    print(f"{len(episodes)} épisodes à fabriquer", file=sys.stderr)


def envoyer(rid: str, fichiers: list[str]) -> None:
    rel = appel("GET", f"/repos/{DEPOT}/releases/{rid}")
    for f in map(Path, fichiers):
        echec = f.stem.replace("_A_VERIFIER", "") + "_ECHEC_"       # vidéo enfin livrée : l'échec consigné part
        for a in rel.get("assets", []):
            if a["name"] == f.name or (f.suffix == ".mp4" and a["name"].startswith(echec)):
                appel("DELETE", f"/repos/{DEPOT}/releases/assets/{a['id']}")
        type_ = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        url = rel["upload_url"].split("{")[0] + "?name=" + urllib.request.quote(f.name)
        appel("POST", url, f.read_bytes(), {"Content-Type": type_})
        print("envoyé", f.name, f"{f.stat().st_size // 1000} ko")


class _SansSuivre(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def lire_asset(url: str) -> bytes:
    """Contenu d'un fichier de brouillon : l'API renvoie vers une adresse signée, lue sans le jeton."""
    ouvreur = urllib.request.build_opener(_SansSuivre)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                                               "Accept": "application/octet-stream"})
    adresse = []

    def ouvrir():
        if adresse:
            return urllib.request.urlopen(adresse[0], timeout=120)
        try:
            return ouvreur.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            adresse.append(e.headers["Location"])
            return urllib.request.urlopen(adresse[0], timeout=120)
    return reessayer(ouvrir)


def echec(rid: str, lot: str, ep: str) -> None:
    """Consigne l'échec dans le brouillon du jour : ce qui a manqué, et l'empreinte qui évite de le retenter
    tant que ni le texte ni les règles de voix n'ont changé."""
    e = next(x for x in json.loads(Path(f"tiktok/lots/{lot}.json").read_text(encoding="utf-8"))["episodes"] if x["id"] == ep)
    journal = ""
    for nom in ("tri.txt", "montage.txt"):
        f = Path("tiktok") / ep / "voix_cb" / nom
        if f.exists():
            texte = f.read_text(encoding="utf-8")
            journal += texte[texte.rfind("Réglage retenu"):] if "Réglage retenu" in texte else texte[-3000:]
    rel = appel("GET", f"/repos/{DEPOT}/releases/{rid}")
    for a in rel.get("assets", []):
        if a["name"].startswith(f"{ep}_ECHEC_"):
            appel("DELETE", f"/repos/{DEPOT}/releases/assets/{a['id']}")
    f = Path("/tmp") / f"{ep}_ECHEC_{empreinte(e)}.txt"
    f.write_text(journal or "échec sans journal", encoding="utf-8")
    url = rel["upload_url"].split("{")[0] + "?name=" + urllib.request.quote(f.name)
    appel("POST", url, f.read_bytes(), {"Content-Type": "text/plain"})
    print("échec consigné", f.name)


def legendes() -> None:
    """Met à jour la légende de chaque vidéo déjà livrée quand celle du lot a changé."""
    lots = {}
    for f in Path("tiktok/lots").glob("j*.json"):
        for e in json.loads(f.read_text(encoding="utf-8"))["episodes"]:
            lots[e["id"]] = e.get("legende", "")
    for rel in toutes_releases():
        for a in rel.get("assets", []):
            if not a["name"].endswith("_legende.txt"):
                continue
            ep = a["name"].replace("_A_VERIFIER", "").replace("_legende.txt", "")
            nouvelle = lots.get(ep)
            if nouvelle is None:
                continue
            actuelle = lire_asset(a["url"]).decode("utf-8").strip()
            if actuelle == nouvelle.strip():
                continue
            f = Path("/tmp") / a["name"]
            f.write_text(nouvelle + "\n", encoding="utf-8")
            envoyer(str(rel["id"]), [str(f)])


if __name__ == "__main__":
    if sys.argv[1] == "plan":
        plan()
    elif sys.argv[1] == "envoyer":
        envoyer(sys.argv[2], sys.argv[3:])
    elif sys.argv[1] == "legendes":
        legendes()
    elif sys.argv[1] == "echec":
        echec(sys.argv[2], sys.argv[3], sys.argv[4])
