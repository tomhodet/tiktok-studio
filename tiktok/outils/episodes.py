"""Crée les épisodes d'un lot à partir d'histoires compactes, et la tâche de voix correspondante.

  python3 episodes.py tiktok/lots/j001.json [--voix]      (--voix : ajoute la tâche dans tiktok/voix_cb.json)
Lot : {"nom": "j001", "graines": [1], "episodes": [
   {"id": "j001_grandmere", "perso": "grandmere", "episode": 2, "fin": "Envoie-la à …", "lueurs": [1, 9, 13],
    "accroche": "texte court pour la couverture", "legende": "légende TikTok",
    "phrases": [["Pendant trente ans, j'ai gardé une *lettre*…", 1.3], …]}, …]}
Chaque phrase : [texte affiché (mots forts entre *), pause après]. Le texte lu est le même, sans astérisques.
Réglages de voix, fond, titre de série : tiktok/personnages.json.
"""
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path("tiktok")


def main() -> None:
    lot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    persos = json.loads((RACINE / "personnages.json").read_text(encoding="utf-8"))
    taches = []
    for e in lot["episodes"]:
        p = persos[e["perso"]]
        ep = RACINE / e["id"]
        ep.mkdir(parents=True, exist_ok=True)
        graine = int(hashlib.sha1(e["id"].encode()).hexdigest(), 16) % 97 + 3
        spec = {"serie": p["serie"], "episode": e.get("episode", 1), "voix_role": p["voix_role"], "perso": e["perso"],
                "fin": e["fin"], "tempo_voix": 1.0, "lueurs": e.get("lueurs", [1, 7, len(e["phrases"])]),
                "graine_musique": e.get("graine_musique", graine), "fond": p["fond"], "plein": p.get("plein", False),
                "accroche": e.get("accroche", ""), "legende": e.get("legende", ""),
                "phrases": [{"n": i + 1, "affiche": a, "voix": a.replace("*", ""), "pause": pause, "plan": "fond"}
                            for i, (a, pause) in enumerate(e["phrases"])]}
        spec["phrases"][-1]["pause"] = 0.0
        (ep / "script.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        taches.append({"nom": f"{e['id']}_r1", "episode": str(ep), "phrases": "toutes", "configs": p["configs"],
                       "graines": lot.get("graines", [1]), "lots": lot.get("lots_par_episode", 2), "whisper": "medium"})
        mots = sum(len(a.split()) for a, _ in e["phrases"])
        print(f"{e['id']} : {len(e['phrases'])} phrases, {mots} mots")
    if "--voix" in sys.argv:
        v = json.loads((RACINE / "voix_cb.json").read_text(encoding="utf-8"))
        for t in v["taches"]:
            t["actif"] = False
        noms = {t["nom"] for t in taches}
        v["taches"] = [t for t in v["taches"] if t["nom"] not in noms] + taches
        (RACINE / "voix_cb.json").write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
        print(len(taches), "tâches de voix ajoutées")


if __name__ == "__main__":
    main()
