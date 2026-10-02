"""Publication automatique sur TikTok via Upload-Post (https://upload-post.com), lancée chaque jour par
.github/workflows/publier.yml. Les vidéos livrées dans les brouillons « jour-NNN » sont programmées à l'avance,
5 par jour, aux heures de tiktok/publication.json, avec leur légende et l'étiquette « contenu généré par l'IA ».

  python3 tiktok/outils/publier.py            programme les jours livrés dans la fenêtre (horizon_jours)
  python3 tiktok/outils/publier.py essai      envoie une seule vidéo en privé (SELF_ONLY), pour tester
Variables : GH_TOKEN, GITHUB_REPOSITORY, UPLOAD_POST_KEY.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from releases import lire_asset, toutes_releases  # noqa: E402

ETAT = Path("tiktok/publication.json")


def envoyer(video: Path, legende: str, quand: dt.datetime | None, conf: dict, prive: bool = False) -> str:
    cmd = ["curl", "-sS", "-X", "POST", "https://api.upload-post.com/api/upload",
           "-H", f"Authorization: Apikey {os.environ['UPLOAD_POST_KEY']}",
           "-F", f"video=@{video}", "-F", f"title={legende}", "-F", f"user={conf['profil']}",
           "-F", "platform[]=tiktok", "-F", "is_aigc=true",
           "-F", f"post_mode={conf.get('mode', 'DIRECT_POST')}",
           "-F", f"privacy_level={'SELF_ONLY' if prive else conf.get('visibilite', 'PUBLIC_TO_EVERYONE')}"]
    if quand:
        cmd += ["-F", f"scheduled_date={quand.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    print(r.stdout[:400], r.stderr[:400], flush=True)
    if r.returncode or '"success":false' in r.stdout.replace(" ", ""):
        raise SystemExit(f"échec de l'envoi de {video.name}")
    return r.stdout


def episodes_livres() -> dict[str, dict]:
    """jour -> {perso: (asset vidéo, asset légende)} pour chaque brouillon complet ou partiel."""
    jours = {}
    for rel in toutes_releases():
        if not rel["tag_name"].startswith("jour-"):
            continue
        noms = {a["name"]: a for a in rel.get("assets", [])}
        for nom, a in noms.items():
            if not nom.endswith(".mp4"):
                continue
            ep = nom[:-4]
            leg = noms.get(f"{ep}_legende.txt")
            base = ep.replace("_A_VERIFIER", "")
            jour, perso = base.split("_", 1)
            jours.setdefault(jour, {})[perso] = (a, leg, ep != base)
    return jours


def main() -> None:
    conf = json.loads(ETAT.read_text(encoding="utf-8"))
    fuseau = ZoneInfo(conf.get("fuseau", "Europe/Paris"))
    livres = episodes_livres()
    if len(sys.argv) > 1 and sys.argv[1] == "essai":
        jour = sorted(livres)[0]
        perso = sorted(livres[jour])[0]
        a, leg, _ = livres[jour][perso]
        f = Path("/tmp") / a["name"]
        f.write_bytes(lire_asset(a["url"]))
        envoyer(f, lire_asset(leg["url"]).decode().strip() if leg else "", None, conf, prive=True)
        print("essai envoyé en privé :", a["name"])
        return
    if not conf.get("actif"):
        print("publication automatique désactivée (\"actif\": false dans tiktok/publication.json)")
        return
    debut = dt.date.fromisoformat(conf["debut"])
    premier = int(conf["premier_lot"][1:])
    aujourdhui = dt.datetime.now(fuseau).date()
    fait = set(conf.get("programmes", []))
    for k in range(premier, 181):
        jour = f"j{k:03d}"
        date = debut + dt.timedelta(days=k - premier)
        if date < aujourdhui or (date - aujourdhui).days > conf.get("horizon_jours", 7):
            continue
        for perso, heure in conf["heures"].items():
            cle = f"{jour}_{perso}"
            if cle in fait or perso not in livres.get(jour, {}):
                continue
            a, leg, a_verifier = livres[jour][perso]
            if a_verifier and not conf.get("publier_a_verifier", False):
                print("à vérifier, non programmé :", cle)
                continue
            hh, mm = map(int, heure.split(":"))
            quand = dt.datetime(date.year, date.month, date.day, hh, mm, tzinfo=fuseau)
            if quand < dt.datetime.now(fuseau) + dt.timedelta(minutes=20):
                continue
            f = Path("/tmp") / a["name"]
            f.write_bytes(lire_asset(a["url"]))
            envoyer(f, lire_asset(leg["url"]).decode().strip() if leg else "", quand, conf)
            fait.add(cle)
            conf["programmes"] = sorted(fait)
            ETAT.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
            print("programmé", cle, quand.isoformat(), flush=True)
            f.unlink()


if __name__ == "__main__":
    main()
