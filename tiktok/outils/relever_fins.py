"""Relève le dernier mot de chaque phrase quand il est trop faible (fin murmurée qui se perdrait sous la
musique et que la vérification finale ne retrouverait pas). À lancer juste après « choisir_voix --assembler ».

  python3 relever_fins.py <episode> [seuil_db=-8] [gain_max_db=9]
Le mot est mesuré sur sa durée (mots détachés par une apostrophe recollés), puis relevé jusqu'à 6 dB sous
le niveau moyen de la phrase, avec une rampe de 40 ms (pas de saut audible).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

EP = Path(sys.argv[1])
SEUIL = float(sys.argv[2]) if len(sys.argv) > 2 else -8.0
GAIN_MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 9.0


def main() -> None:
    fin = EP / "voix" / "finale"
    for p in json.loads((fin / "phrases.json").read_text(encoding="utf-8")):
        f = fin / f"s{p['n']:02d}.wav"
        y, sr = sf.read(str(f))
        mots = [m for m in p["mots"] if re.search(r"\w", m["mot"])]
        if not mots:
            continue
        k = len(mots) - 1
        while k > 0 and mots[k]["mot"][:1] in "'’-":      # « aujourd » + « 'hui » = un seul mot
            k -= 1
        a, b = int(mots[k]["debut"] * sr), min(len(y), int(mots[-1]["fin"] * sr))
        if b - a < int(0.05 * sr):
            continue
        tot = 20 * np.log10(np.sqrt(np.mean(y ** 2)) + 1e-9)
        mot = 20 * np.log10(np.sqrt(np.mean(y[a:b] ** 2)) + 1e-9)
        ecart = mot - tot
        if ecart >= SEUIL:
            continue
        gain = min(-6 - ecart, GAIN_MAX)
        g = np.ones(len(y))
        r = int(0.04 * sr)
        G = 10 ** (gain / 20)
        debut = max(0, a - r)
        g[debut:a] = np.linspace(1, G, a - debut)
        g[a:] = G
        z = y * g
        if np.abs(z).max() > 0.98:
            z *= 0.98 / np.abs(z).max()
        sf.write(str(f), z.astype(np.float32), sr, subtype="PCM_16")
        print(f"s{p['n']:02d} « {''.join(m['mot'] for m in mots[k:])} » {ecart:.1f} dB -> +{gain:.1f} dB", flush=True)


if __name__ == "__main__":
    main()
