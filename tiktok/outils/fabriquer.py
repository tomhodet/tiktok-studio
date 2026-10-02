"""Fabrication complète d'un épisode, d'un seul tenant (GitHub Actions, dépôt public) :
prises de voix, tri expressif, reprises des phrases sans prise valable, débit posé, fins relevées, montage,
vérification de ce que le spectateur entend, livraison (vidéo compressée, couverture, légende).

  python3 tiktok/outils/fabriquer.py <lot> <episode_id> <dossier_livraison>
  ex. python3 tiktok/outils/fabriquer.py j002 j002_grandmere /tmp/livraison

Les prises restent sur la machine de calcul : rien n'est publié en dehors de la vidéo finale.
Code de sortie : 0 livré et vérifié, 4 livré mais à vérifier à l'oreille, 2 voix incomplète, 3 montage raté.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

PY = "/tmp/tts/bin/python"
LOT, ID, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
EP = Path("tiktok") / ID
VCB = EP / "voix_cb"
TOURS_MAX = 6          # tours de prises par exécution ; une reprise (cache) continue avec de nouvelles graines


def run(*cmd, sortie: Path | None = None) -> int:
    print("$", " ".join(map(str, cmd)), flush=True)
    if sortie:
        with open(sortie, "a", encoding="utf-8") as f:
            return subprocess.run(list(map(str, cmd)), stdout=f, stderr=subprocess.STDOUT).returncode
    return subprocess.run(list(map(str, cmd))).returncode


def prises(nom: str, phrases, graines: list[int], configs) -> None:
    spec = {"taches": [{"nom": nom, "episode": str(EP), "phrases": phrases, "configs": configs,
                        "graines": graines, "lots": 1, "whisper": "medium"}]}
    Path("tiktok/voix_cb.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
    run(PY, "tiktok/outils/voix_cb.py", nom, 0, sortie=VCB / f"journal_{nom}.txt")


def trier(ref: str) -> list[int]:
    shutil.rmtree(EP / "voix" / "finale", ignore_errors=True)
    (VCB / "tri.txt").write_text("", encoding="utf-8")
    run(PY, "tiktok/outils/choisir_voix.py", EP, "--par-ref", "--expressif", f"--config={ref},0,0", "--assembler",
        sortie=VCB / "tri.txt")
    choix = json.loads((VCB / "choix.json").read_text(encoding="utf-8")) if (VCB / "choix.json").exists() else {}
    if not choix:
        return [-1]
    return choix.get("manquantes", [])


def voix_complete(ref: str, configs, tour0: int, n: int = TOURS_MAX) -> tuple[bool, int]:
    """Prises jusqu'à ce que chaque phrase en ait une valable (au plus n tours de 2 graines, graines jamais
    réutilisées : le tour t prend les graines 2t+1 et 2t+2)."""
    manquantes = trier(ref) if any(VCB.glob("*/*.json")) else "toutes"
    t = tour0
    while manquantes and t < tour0 + n:
        prises(f"{ID}_v{t + 1}", "toutes" if manquantes in ("toutes", [-1]) else manquantes, [2 * t + 1, 2 * t + 2], configs)
        manquantes = trier(ref)
        print(f"tour {t + 1} : phrases sans prise valable {manquantes}", flush=True)
        t += 1
    return not manquantes, t


def monter_et_verifier() -> dict:
    run(PY, "tiktok/outils/poser_debit.py", EP, sortie=VCB / "tri.txt")
    run(PY, "tiktok/outils/relever_fins.py", EP, sortie=VCB / "tri.txt")
    shutil.rmtree(EP / "_travail", ignore_errors=True)
    if run(PY, "tiktok/outils/montage.py", EP, "finale", sortie=VCB / "montage.txt"):
        print((VCB / "montage.txt").read_text(encoding="utf-8")[-3000:])
        sys.exit(3)
    (EP / "verif").mkdir(exist_ok=True)
    run("ffmpeg", "-v", "error", "-y", "-i", EP / f"{ID}_finale.mp4", "-vn", "-ac", "1", "-ar", "16000",
        EP / "verif" / "voix_montee.flac")
    shutil.copy(EP / "_travail" / "chrono.json", EP / "verif" / "chrono.json")
    (EP / "verif" / "journal.txt").write_text("", encoding="utf-8")
    run(PY, "tiktok/outils/verif_voix.py", EP, sortie=EP / "verif" / "journal.txt")
    return json.loads((EP / "verif" / "rapport.json").read_text(encoding="utf-8"))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    VCB.mkdir(parents=True, exist_ok=True)
    run("python3", "tiktok/outils/episodes.py", f"tiktok/lots/{LOT}.json")
    script = json.loads((EP / "script.json").read_text(encoding="utf-8"))
    perso = json.loads(Path("tiktok/personnages.json").read_text(encoding="utf-8"))[script["perso"]]
    configs = perso.get("configs_production", perso["configs"])
    ref = configs[0][0]

    deja = len(list(VCB.glob(f"{ID}_v*")))      # prises reprises d'une exécution précédente (cache)
    ok, t = voix_complete(ref, configs, deja)
    if not ok:
        print((VCB / "tri.txt").read_text(encoding="utf-8")[-4000:])
        sys.exit(2)
    rapport = monter_et_verifier()
    if not rapport["ok"]:
        # Phrases mal entendues : leurs prises sont écartées, on trie à nouveau (autres prises ou nouvelles)
        choix = json.loads((VCB / "choix.json").read_text(encoding="utf-8"))["choix"]
        fautives = [p["n"] for p in rapport["phrases"] if not p["ok"]]
        exclues = [choix[str(n)] for n in fautives if str(n) in choix]
        fx = VCB / "exclues.json"
        anciennes = json.loads(fx.read_text(encoding="utf-8")) if fx.exists() else []
        fx.write_text(json.dumps(anciennes + exclues, ensure_ascii=False), encoding="utf-8")
        print(f"vérification : phrases {fautives} à reprendre, prises écartées {exclues}", flush=True)
        ok, t = voix_complete(ref, configs, t, 3)
        if ok:
            rapport = monter_et_verifier()
    print((EP / "verif" / "journal.txt").read_text(encoding="utf-8"))
    run("bash", "tiktok/outils/livrer.sh", EP, OUT)
    suffixe = "" if rapport["ok"] else "_A_VERIFIER"
    shutil.copy(EP / "verif" / "journal.txt", OUT / f"{ID}_verification.txt")
    if suffixe:
        for f in OUT.glob(f"{ID}*"):
            f.rename(f.with_name(f.name.replace(ID, ID + suffixe, 1)))
    print("LIVRÉ" + (" (à vérifier à l'oreille)" if suffixe else ""), ID, flush=True)
    sys.exit(4 if suffixe else 0)


if __name__ == "__main__":
    main()
