"""Voix seules d'un épisode (sans montage) : prises, tri, débit, fins ; puis archive chiffrée de voix/finale.
  python3 tiktok/outils/voix_seules.py <lot> <episode_id> <dossier_sortie>
Sortie : <dossier_sortie>/<episode_id>_voix.tar.enc (COFFRE_CLE) contenant tiktok/<episode_id>/voix/finale/.
Code de sortie : 0 OK, 2 voix incomplète.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fabriquer as F  # noqa: E402  (lit sys.argv : lot, épisode, dossier)


def main() -> None:
    F.OUT.mkdir(parents=True, exist_ok=True)
    F.VCB.mkdir(parents=True, exist_ok=True)
    F.run("python3", "tiktok/outils/episodes.py", f"tiktok/lots/{F.LOT}.json")
    import json
    script = json.loads((F.EP / "script.json").read_text(encoding="utf-8"))
    perso = json.loads(Path("tiktok/personnages.json").read_text(encoding="utf-8"))[script["perso"]]
    configs = perso.get("configs_production", perso["configs"])
    deja = len(list(F.VCB.glob(f"{F.ID}_v*")))
    ok, _ = F.voix_complete(configs[0][0], configs, deja)
    if not ok:
        print((F.VCB / "tri.txt").read_text(encoding="utf-8")[-4000:])
        sys.exit(2)
    F.run(F.PY, "tiktok/outils/poser_debit.py", F.EP, sortie=F.VCB / "tri.txt")
    F.run(F.PY, "tiktok/outils/relever_fins.py", F.EP, sortie=F.VCB / "tri.txt")
    tar = F.OUT / f"{F.ID}_voix.tar.enc"
    subprocess.run(f"tar -c tiktok/{F.ID}/voix/finale tiktok/{F.ID}/script.json | openssl enc -aes-256-cbc -pbkdf2 "
                   f"-iter 200000 -salt -out '{tar}' -pass env:COFFRE_CLE", shell=True, check=True)
    print("VOIX PRÊTES", F.ID, tar.stat().st_size // 1000, "ko", flush=True)


if __name__ == "__main__":
    main()
