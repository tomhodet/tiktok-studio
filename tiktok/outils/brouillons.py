"""Brouillons TikTok automatiques (gratuit, API officielle de TikTok, droit video.upload) : chaque matin, les
5 vidéos du jour arrivent dans la boîte de réception TikTok de Tom, et leurs légendes sur son téléphone (ntfy).
Tom ouvre chaque brouillon, colle la légende, coche « contenu généré par l'IA » et publie.

  python3 tiktok/outils/brouillons.py autoriser     échange le code d'autorisation (tiktok/tiktok_code.txt)
  python3 tiktok/outils/brouillons.py jour          envoie les brouillons du jour prévu par tiktok/brouillons.json
  python3 tiktok/outils/brouillons.py essai         envoie une seule vidéo en brouillon, pour tester
Variables : GH_TOKEN, GITHUB_REPOSITORY, TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET.
Jeton : tiktok/tiktok_jeton.json (chiffré dans le dépôt, déchiffré par le workflow le temps du calcul).
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from releases import lire_asset, toutes_releases  # noqa: E402

API = "https://open.tiktokapis.com"
REDIRECTION = "https://github.com/tomhodet/tiktok-studio"
JETON = Path("tiktok/tiktok_jeton.json")
ETAT = Path("tiktok/brouillons.json")
NOMS = {"grandmere": "grand-mère", "grandpere": "grand-père", "pere": "père", "mere": "mère", "fou": "fou"}


def requete(methode: str, url: str, donnees=None, entetes=None, forme=False) -> dict:
    h = dict(entetes or {})
    corps = None
    if donnees is not None:
        if forme:
            corps = urllib.parse.urlencode(donnees).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            corps = json.dumps(donnees).encode()
            h["Content-Type"] = "application/json; charset=UTF-8"
    req = urllib.request.Request(url, data=corps, headers=h, method=methode)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        print("erreur", e.code, e.read()[:600].decode("utf-8", "replace"), flush=True)
        raise


def jeton_oauth(champs: dict) -> None:
    rep = requete("POST", f"{API}/v2/oauth/token/", {"client_key": os.environ["TIKTOK_CLIENT_KEY"],
                                                      "client_secret": os.environ["TIKTOK_CLIENT_SECRET"], **champs},
                  {"Cache-Control": "no-cache"}, forme=True)
    if "access_token" not in rep:
        raise SystemExit(f"jeton refusé : {rep}")
    rep["obtenu"] = int(time.time())
    JETON.write_text(json.dumps(rep), encoding="utf-8")
    print("jeton obtenu, droits :", rep.get("scope"), flush=True)


def autoriser() -> None:
    code = Path("tiktok/tiktok_code.txt").read_text(encoding="utf-8").strip()
    if "code=" in code:                       # adresse complète recopiée par Tom
        code = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)["code"][0]
    jeton_oauth({"code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECTION})


def acces() -> str:
    j = json.loads(JETON.read_text(encoding="utf-8"))
    if time.time() > j["obtenu"] + j.get("expires_in", 86400) - 600:
        jeton_oauth({"grant_type": "refresh_token", "refresh_token": j["refresh_token"]})
        j = json.loads(JETON.read_text(encoding="utf-8"))
    return j["access_token"]


def brouillon(video: Path) -> str:
    """Envoi en un seul morceau (vidéos de moins de 64 Mo) vers la boîte de réception TikTok."""
    taille = video.stat().st_size
    rep = requete("POST", f"{API}/v2/post/publish/inbox/video/init/",
                  {"source_info": {"source": "FILE_UPLOAD", "video_size": taille, "chunk_size": taille,
                                   "total_chunk_count": 1}},
                  {"Authorization": f"Bearer {acces()}"})
    url, pid = rep["data"]["upload_url"], rep["data"]["publish_id"]
    req = urllib.request.Request(url, data=video.read_bytes(), method="PUT",
                                 headers={"Content-Type": "video/mp4", "Content-Length": str(taille),
                                          "Content-Range": f"bytes 0-{taille - 1}/{taille}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        print("envoyé", video.name, r.status, pid, flush=True)
    return pid


def prevenir(sujet: str, titre: str, texte: str) -> None:
    """Notification sur le téléphone de Tom (appli ntfy, gratuite), légende prête à copier."""
    corps = json.dumps({"topic": sujet, "title": titre, "message": texte, "tags": ["movie_camera"]}).encode()
    req = urllib.request.Request("https://ntfy.sh/", data=corps, method="POST",
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()


def videos_du_jour(jour: str) -> dict:
    for rel in toutes_releases():
        if rel["tag_name"] == f"jour-{jour[1:]}":
            noms = {a["name"]: a for a in rel.get("assets", [])}
            res = {}
            for nom, a in noms.items():
                if nom.endswith(".mp4"):
                    ep = nom[:-4]
                    perso = ep.replace("_A_VERIFIER", "").split("_", 1)[1]
                    res[perso] = (a, noms.get(f"{ep}_legende.txt"), "_A_VERIFIER" in ep)
            return res
    return {}


def envoyer_jour(jour: str, conf: dict, seul: bool = False) -> None:
    videos = videos_du_jour(jour)
    ordre = [p for p in conf["ordre"] if p in videos][:1 if seul else 5]
    if not ordre:
        prevenir(conf["ntfy"], f"Jour {int(jour[1:])} : pas encore prêt", "Les vidéos de ce jour ne sont pas encore fabriquées.")
        return
    for k, perso in enumerate(ordre, 1):
        a, leg, a_verifier = videos[perso]
        f = Path("/tmp") / a["name"]
        f.write_bytes(lire_asset(a["url"]))
        brouillon(f)
        f.unlink()
        legende = lire_asset(leg["url"]).decode("utf-8").strip() if leg else ""
        titre = f"Jour {int(jour[1:])}, {k}/{len(ordre)} : {NOMS.get(perso, perso)}" + (" (à écouter avant)" if a_verifier else "")
        prevenir(conf["ntfy"], titre, legende)
        conf.setdefault("envoyes", []).append(f"{jour}_{perso}")
        time.sleep(12)                        # 6 requêtes par minute au plus par jeton


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "jour"
    if action == "autoriser":
        autoriser()
        return
    conf = json.loads(ETAT.read_text(encoding="utf-8"))
    if action == "essai" or conf.pop("demande", "") == "essai":     # demande posée dans brouillons.json
        envoyer_jour(conf["premier_lot"], conf, seul=True)
    elif conf.get("actif"):
        aujourdhui = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
        k = int(conf["premier_lot"][1:]) + (aujourdhui - dt.date.fromisoformat(conf["debut"])).days
        jour = f"j{k:03d}"
        if 1 <= k <= 180 and not any(e.startswith(jour) for e in conf.get("envoyes", [])):
            envoyer_jour(jour, conf)
    else:
        print("brouillons automatiques désactivés (\"actif\": false)")
    ETAT.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
