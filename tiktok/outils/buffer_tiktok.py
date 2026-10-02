"""Publication automatique et gratuite sur TikTok (compte professionnel) par l'API de Buffer (offre gratuite :
10 publications programmées à la fois par canal, 3 000 requêtes par mois). Lancé deux fois par jour par
.github/workflows/publier.yml : la file Buffer est remplie jusqu'à 10 vidéos d'avance (2 jours à 5 par jour).

  python3 tiktok/outils/buffer_tiktok.py decouvrir   organisations, canaux et schéma utile (journal du workflow)
  python3 tiktok/outils/buffer_tiktok.py remplir     programme les prochains créneaux libres
Variables : GH_TOKEN, GITHUB_REPOSITORY, BUFFER_API_KEY. Réglages et suivi : tiktok/buffer.json.

Buffer va chercher chaque vidéo à une adresse publique : la vidéo est déposée dans la publication GitHub
publique « a-publier » juste avant, puis retirée deux jours après son horaire de publication.
"""
import datetime as dt
import json
import mimetypes
import os
import sys
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from releases import DEPOT, appel, lire_asset, toutes_releases  # noqa: E402

ETAT = Path("tiktok/buffer.json")
FILE_MAX = 10


def gql(requete: str, variables: dict | None = None) -> dict:
    corps = json.dumps({"query": requete, "variables": variables or {}}).encode()
    req = urllib.request.Request("https://api.buffer.com", data=corps, method="POST",
                                 headers={"Authorization": f"Bearer {os.environ['BUFFER_API_KEY']}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        rep = json.loads(r.read())
    if rep.get("errors"):
        print("erreurs GraphQL :", json.dumps(rep["errors"], ensure_ascii=False)[:1500], flush=True)
    return rep.get("data") or {}


def schema(nom: str) -> None:
    d = gql("""query($n: String!) { __type(name: $n) { name kind inputFields { name type { name kind ofType { name kind } } }
               fields { name } enumValues { name } } }""", {"n": nom})
    print(nom, json.dumps(d.get("__type"), ensure_ascii=False), flush=True)


def decouvrir(conf: dict) -> None:
    d = gql("{ account { organizations { id name } } }")
    orgs = (d.get("account") or {}).get("organizations") or []
    print("organisations :", orgs, flush=True)
    for o in orgs:
        c = gql("query($o: OrganizationId!) { channels(input: {organizationId: $o}) { id name service } }", {"o": o["id"]})
        print("canaux :", c.get("channels"), flush=True)
        for ch in c.get("channels") or []:
            if ch.get("service", "").lower() == "tiktok":
                conf["organisation"], conf["canal"] = o["id"], ch["id"]
    for t in ("CreatePostInput", "PostsInput", "PostsFiltersInput", "AssetsInput", "VideoAssetInput",
              "PostInputMetaData", "TikTokPostMetadataInput", "SchedulingType", "ShareMode", "PostStatus"):
        schema(t)


def public_url(fichier: Path) -> str:
    """Dépose la vidéo dans la publication publique « a-publier » et renvoie son adresse de téléchargement."""
    rels = {r["tag_name"]: r for r in toutes_releases()}
    rel = rels.get("a-publier") or appel("POST", f"/repos/{DEPOT}/releases",
                                         {"tag_name": "a-publier", "name": "Vidéos en cours de publication",
                                          "body": "Fichiers temporaires lus par Buffer, retirés après publication."})
    for a in rel.get("assets", []):
        if a["name"] == fichier.name:
            return a["browser_download_url"]
    url = rel["upload_url"].split("{")[0] + "?name=" + urllib.request.quote(fichier.name)
    a = appel("POST", url, fichier.read_bytes(), {"Content-Type": mimetypes.guess_type(fichier.name)[0] or "video/mp4"})
    return a["browser_download_url"]


def nettoyer(conf: dict) -> None:
    """Retire les vidéos publiques dont l'horaire est passé depuis plus de deux jours."""
    limite = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)
    vieux = {p["fichier"] for p in conf.get("programmes", []) if dt.datetime.fromisoformat(p["quand"]) < limite}
    for rel in toutes_releases():
        if rel["tag_name"] == "a-publier":
            for a in rel.get("assets", []):
                if a["name"] in vieux:
                    appel("DELETE", f"/repos/{DEPOT}/releases/assets/{a['id']}")
                    print("retiré", a["name"], flush=True)


def livrees() -> dict:
    res = {}
    for rel in toutes_releases():
        if not rel["tag_name"].startswith("jour-"):
            continue
        noms = {a["name"]: a for a in rel.get("assets", [])}
        for nom, a in noms.items():
            if nom.endswith(".mp4"):
                ep = nom[:-4]
                base = ep.replace("_A_VERIFIER", "")
                res[base] = (a, noms.get(f"{ep}_legende.txt"), base != ep)
    return res


def creer(conf: dict, texte: str, url: str, quand: dt.datetime) -> str:
    d = gql("""mutation($i: CreatePostInput!) { createPost(input: $i) {
                 ... on PostActionSuccess { post { id dueAt } } ... on MutationError { message } } }""",
            {"i": {"channelId": conf["canal"], "text": texte, "schedulingType": "automatic", "mode": "customScheduled",
                   "dueAt": quand.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                   "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": conf.get("vignette_ms", 1500)}}}],
                   **({"metadata": {"tiktok": {"isAiGenerated": True}}} if conf.get("etiquette_ia", True) else {})}})
    r = d.get("createPost") or {}
    if "post" not in r:
        raise SystemExit(f"Buffer a refusé la publication : {r or d}")
    return r["post"]["id"]


def remplir(conf: dict) -> None:
    fuseau = ZoneInfo(conf.get("fuseau", "Europe/Paris"))
    maintenant = dt.datetime.now(fuseau)
    a_venir = [p for p in conf.get("programmes", []) if dt.datetime.fromisoformat(p["quand"]) > maintenant]
    place = FILE_MAX - len(a_venir)
    deja = {p["episode"] for p in conf.get("programmes", [])}
    videos = livrees()
    debut, premier = dt.date.fromisoformat(conf["debut"]), int(conf["premier_lot"][1:])
    k = max(premier, premier + (maintenant.date() - debut).days)
    while place > 0 and k <= 180:
        date = debut + dt.timedelta(days=k - premier)
        for perso, heure in conf["heures"].items():
            ep = f"j{k:03d}_{perso}"
            hh, mm = map(int, heure.split(":"))
            quand = dt.datetime(date.year, date.month, date.day, hh, mm, tzinfo=fuseau)
            if place <= 0 or ep in deja or quand < maintenant + dt.timedelta(minutes=30):
                continue
            if ep not in videos:
                print("pas encore fabriquée :", ep, flush=True)
                continue
            a, leg, a_verifier = videos[ep]
            if a_verifier and not conf.get("publier_a_verifier", False):
                print("à vérifier, non programmée :", ep, flush=True)
                continue
            f = Path("/tmp") / f"{ep}.mp4"
            f.write_bytes(lire_asset(a["url"]))
            texte = lire_asset(leg["url"]).decode("utf-8").strip() if leg else ""
            pid = creer(conf, texte, public_url(f), quand)
            conf.setdefault("programmes", []).append({"episode": ep, "quand": quand.isoformat(), "post": pid,
                                                      "fichier": f.name})
            ETAT.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
            print("programmée", ep, quand.isoformat(), pid, flush=True)
            f.unlink()
            place -= 1
        k += 1


def main() -> None:
    conf = json.loads(ETAT.read_text(encoding="utf-8"))
    action = sys.argv[1] if len(sys.argv) > 1 else "remplir"
    if action == "decouvrir" or conf.pop("demande", "") == "decouvrir" or not conf.get("canal"):
        decouvrir(conf)
    elif conf.get("actif"):
        nettoyer(conf)
        remplir(conf)
    else:
        print("publication automatique désactivée (\"actif\": false)")
    ETAT.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
