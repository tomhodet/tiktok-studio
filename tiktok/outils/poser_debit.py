"""Pose la voix : une phrase dite trop vite (débit en lettres par seconde de parole au-dessus du plafond du
personnage) est ralentie sans changer la hauteur (rubberband), de 15 % au plus. Les temps des mots sont mis à
l'échelle pour les sous-titres. À lancer juste après « choisir_voix --assembler ».

  python3 poser_debit.py <episode> [plafond]
Plafond : argument, sinon « debit_max » du personnage dans tiktok/personnages.json, sinon 14,5.
"""
import json
import subprocess
import sys
from pathlib import Path

EP = Path(sys.argv[1])
RALENTI_MAX = 0.85


def main() -> None:
    script = json.loads((EP / "script.json").read_text(encoding="utf-8"))
    perso = json.loads(Path("tiktok/personnages.json").read_text(encoding="utf-8")).get(script.get("perso", ""), {})
    plafond = float(sys.argv[2]) if len(sys.argv) > 2 else float(perso.get("debit_max", 14.5))
    textes = {p["n"]: p["voix"] for p in script["phrases"]}
    fin = EP / "voix" / "finale"
    phrases = json.loads((fin / "phrases.json").read_text(encoding="utf-8"))
    for p in phrases:
        mots = p["mots"]
        if len(mots) < 2:
            continue
        parole = mots[-1]["fin"] - mots[0]["debut"]
        lettres = sum(ch.isalpha() for ch in textes.get(p["n"], p["entendu"]))
        debit = lettres / max(parole, 0.5)
        if debit <= plafond:
            continue
        tempo = max(float(perso.get("ralenti_max", RALENTI_MAX)), plafond / debit)
        f = fin / f"s{p['n']:02d}.wav"
        tmp = f.with_suffix(".tmp.wav")
        for filtre in (f"rubberband=tempo={tempo:.4f}", f"atempo={tempo:.4f}"):    # atempo si ffmpeg sans rubberband
            if subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-af", filtre, "-c:a", "pcm_s16le",
                               str(tmp)]).returncode == 0:
                break
        else:
            raise SystemExit(f"ralenti impossible pour {f}")
        tmp.replace(f)
        for m in mots:
            m["debut"] = round(m["debut"] / tempo, 3)
            m["fin"] = round(m["fin"] / tempo, 3)
        p["duree"] = round(p["duree"] / tempo, 3)
        p["ralenti"] = round(tempo, 3)
        print(f"s{p['n']:02d} débit {debit:.1f} -> {debit * tempo:.1f} lettres/s (tempo {tempo:.2f})")
    (fin / "phrases.json").write_text(json.dumps(phrases, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
