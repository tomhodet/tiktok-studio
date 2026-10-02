"""Choix des prises de voix (Chatterbox) d'un épisode, à partir des mesures faites sur GitHub Actions.

  python choisir_voix.py <episode> [--assembler] [--config ref,exag,cfg]

1. Filtre strict (aucun mot manquant ou coupé) : transcription identique au texte (à une faute
   de transcription près), premier et dernier mot bien dits, pas de fin brusque, marge après le
   dernier mot, pas de silence anormal au milieu, pas de mot douteux.
2. Note de chaque prise : naturel (UTMOS), expressivité (étendue de la hauteur, dans une plage
   vivante mais pas désordonnée), intonation finale descendante sur les phrases qui se terminent
   par un point, débit posé.
3. Choix d'un seul réglage (référence, exagération, cfg) pour tout l'épisode : même timbre et même
   diction d'une phrase à l'autre. Puis, pour chaque phrase, la meilleure prise de ce réglage.
4. --assembler : copie les prises retenues dans <episode>/voix/finale (s01.wav…, phrases.json,
   bilan.json), prêtes pour montage.py (« python3 montage.py <episode> finale »).
Les phrases sans prise valable sont listées : elles repartent en génération (plus de graines).
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from texte_oral import mots_proches, norm  # noqa: E402

EP = Path(sys.argv[1])
ASSEMBLER = "--assembler" in sys.argv
FORCE = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--config=")), None)
PAR_REF = "--par-ref" in sys.argv            # regroupe par référence seulement (exagération et cfg mélangées)
EXPRESSIF = "--expressif" in sys.argv        # note qui favorise les prises les plus vivantes


def ecart_texte(ref: str, hyp: str) -> tuple[int, int]:
    """(mots manquants ou en trop, mots différents) après tolérance."""
    r, h = norm(ref), norm(hyp)
    n, m = len(r), len(h)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = i
    for j in range(m + 1):
        d[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (0 if mots_proches(r[i - 1], h[j - 1]) else 1))
    # remonte pour séparer insertions/suppressions et substitutions
    i, j, indel, sub = n, m, 0, 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and d[i][j] == d[i - 1][j - 1] + (0 if mots_proches(r[i - 1], h[j - 1]) else 1):
            sub += 0 if mots_proches(r[i - 1], h[j - 1]) else 1
            i, j = i - 1, j - 1
        elif i > 0 and d[i][j] == d[i - 1][j] + 1:
            indel, i = indel + 1, i - 1
        else:
            indel, j = indel + 1, j - 1
    return indel, sub


def charger() -> list[dict]:
    # prises écartées après une vérification ratée (voix_cb/exclues.json : noms de prises)
    fx = EP / "voix_cb" / "exclues.json"
    exclues = set(json.loads(fx.read_text(encoding="utf-8"))) if fx.exists() else set()
    res = []
    for f in sorted((EP / "voix_cb").glob("*/*.json")):
        if f.stem in exclues:
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        r["fichier"] = str(f.with_suffix(".flac"))
        res.append(r)
    return res


def fin_eteinte(r: dict) -> bool:
    """La prise s'arrête juste après le dernier mot, mais le son s'était déjà éteint (pas de mot coupé) :
    les 50 dernières millisecondes sont au moins 38 dB sous la crête."""
    import soundfile as sf
    try:
        y, sr = sf.read(r["fichier"], dtype="float32")
    except Exception:
        return False
    if y.ndim > 1:
        y = y.mean(axis=1)
    queue = y[-int(0.05 * sr):]
    return len(queue) > 0 and 20 * np.log10(np.sqrt(np.mean(queue ** 2)) / (np.abs(y).max() + 1e-9) + 1e-9) < -38


def controle(r: dict) -> list[str]:
    defauts = []
    indel, sub = ecart_texte(r["texte"], r["entendu"])
    if indel:
        defauts.append(f"{indel} mot(s) manquant(s) ou en trop")
    if sub:
        defauts.append(f"{sub} mot(s) mal dit(s)")
    t, e = norm(r["texte"]), norm(r["entendu"])
    if not (t and e and mots_proches(t[0], e[0])):
        defauts.append("premier mot")
    if not (t and e and mots_proches(t[-1], e[-1])):
        defauts.append("dernier mot")
    if r["fin_brusque"] and r["fin_marge"] < 0.3:     # arrêt brutal juste après le dernier mot (sinon : souffle de fin, coupé à l'assemblage)
        defauts.append("fin brusque")
    # fin serrée : acceptée si la dernière syllabe retombe déjà (30 dernières ms à -28 dB sous la crête,
    # le fondu de l'assemblage finit le travail) ; refusée si le son est coupé net
    if r["fin_marge"] < 0.08 and r["fin_brusque"] and not fin_eteinte(r):
        defauts.append("fin trop juste")
    m = r["mots"]
    trous = [m[k + 1]["debut"] - m[k]["fin"] for k in range(len(m) - 1)]
    ponct = {k for k, w in enumerate(m) if re.search(r"[.,;:!?]$", w["mot"])}
    for k, g in enumerate(trous):
        if g > (1.3 if k in ponct else 0.7):
            defauts.append(f"silence de {g:.1f} s après « {m[k]['mot']} »")
    # mot douteux : seulement les vrais mots (Whisper donne aussi des guillemets et des « ! » peu sûrs)
    pm = min((w["proba"] for w in r["mots"] if re.search(r"\w", w["mot"])), default=r["proba_min"])
    if pm < 0.25:
        defauts.append(f"mot douteux (proba {pm})")
    if m and m[0]["debut"] > 0.6:
        defauts.append("attaque tardive")
    if not defauts:
        fin, d = fin_reelle(r)
        r["fin_voix"] = fin
        if d:
            defauts.append(d)
    return defauts


def fin_reelle(r: dict) -> tuple[float | None, str | None]:
    """Instant où la voix s'éteint vraiment après le dernier mot (énergie sous -42 dB pendant 150 ms).
    Renvoie (instant, défaut). Défaut si du son continue après la phrase (le modèle « babille »)."""
    import soundfile as sf
    y, sr = sf.read(r["fichier"], dtype="float32")
    if not r["mots"]:
        return None, "aucun mot"
    hop = int(0.01 * sr)
    rms = np.array([np.sqrt(np.mean(y[i:i + hop] ** 2)) + 1e-9 for i in range(0, len(y) - hop, hop)])
    db = 20 * np.log10(rms / rms.max())
    k0 = int(r["mots"][-1]["fin"] / 0.01)

    def coupe():
        """Repli quand la prise continue après la phrase (clic, souffle, babil) : vrai silence d'au moins
        140 ms (sous -45 dB) qui commence dans le dernier mot ou juste après ; la coupe de l'assemblage
        (fin + 0,12 s, fondu) tombe alors dans ce silence et le reste de la prise est jeté."""
        k1 = int(r["mots"][-1]["debut"] / 0.01) + 15
        for k in range(max(k1, k0 - 40), min(len(db) - 14, k0 + 30)):
            if np.all(db[k:k + 14] < -45):
                r["coupee"] = round(k * 0.01, 2)
                return k * 0.01, None
        return None
    # seuil de silence adapté au bruit de fond de la prise (certaines voix gardent un léger souffle de pièce)
    seuil = min(-30.0, max(-42.0, float(np.percentile(db, 10)) + 6.0))
    calme = 0
    for k in range(max(0, k0 - 5), len(db)):
        calme = calme + 1 if db[k] < seuil else 0
        if calme >= 15:
            fin = (k - 14) * 0.01
            if fin - r["mots"][-1]["fin"] > 0.6:
                return coupe() or (None, f"{fin - r['mots'][-1]['fin']:.1f} s de son après le dernier mot")
            apres = db[k:]
            # Défaut seulement si ce qui reprend dure (≥ 0,2 s au-dessus de -30 dB) : un souffle ou un
            # clic isolé est de toute façon retiré par la coupe douce juste après le dernier mot.
            if len(apres) and np.sum(apres > -25) >= 20:
                return coupe() or (None, "du son reprend après la phrase")
            return fin, None
    reste = (len(db) - k0) * 0.01
    return (len(y) / sr, None) if reste < 0.45 else (coupe() or (None, f"{reste:.1f} s de son après le dernier mot"))


def intonation_finale(r: dict) -> float | None:
    """Mouvement de hauteur (demi-tons) sur le dernier mot : négatif = descend, comme une affirmation."""
    import librosa
    import soundfile as sf
    if not r["mots"]:
        return None
    y, sr = sf.read(r["fichier"], dtype="float32")
    a, b = r["mots"][-1]["debut"], r["mots"][-1]["fin"]
    a = max(0.0, min(a, b - 0.25))
    seg = y[int(a * sr):int(b * sr)]
    if len(seg) < int(0.2 * sr):
        return None
    seg = librosa.resample(seg, orig_sr=sr, target_sr=16000)
    f0, voise, _ = librosa.pyin(seg, fmin=60, fmax=450, sr=16000, frame_length=1024, hop_length=160)
    v = f0[voise]
    if len(v) < 8:
        return None
    k = max(3, len(v) // 3)
    return round(float(12 * np.log2(np.median(v[-k:]) / np.median(v[:k]))), 2)


def note(r: dict, cible_debit: float) -> float:
    s = 0.0
    fin = r.get("intonation_fin")
    if fin is not None and r["texte"].rstrip().endswith("."):
        if -6.0 <= fin <= -1.0:
            s += 0.3        # une affirmation retombe
        elif fin < -7.0:
            s -= 0.3        # chute de plus d'une demi-octave : voix qui grince ou mesure faussée
        elif fin > 1.5:
            s -= 1.0        # fin qui remonte : sonne comme une question
    if r.get("utmos") is not None:
        s += 1.2 * (r["utmos"] - 3.0)
    e = r["etendue_st"]
    if EXPRESSIF:    # priorité à l'émotion : voix qui monte et descend, sans aller jusqu'au chaos
        if e < 3.2:
            s -= (3.2 - e) * 0.6
        elif e <= 9.0:
            s += 0.18 * (min(e, 8.0) - 3.2)
    elif e <= 6.5:   # au-delà, mesure faussée (voix âgée, éraillée : sauts d'octave du détecteur), on ne note pas
        s += -abs(e - 3.2) * 0.6 if e < 3.2 else -max(0.0, e - 5.5) * 0.8   # vivant, sans chaos
    s -= abs(r["debit"] - cible_debit) * 0.25
    s -= 0.3 * ecart_texte(r["texte"], r["entendu"])[1]
    return round(s, 3)


def main() -> None:
    spec = json.loads((EP / "script.json").read_text(encoding="utf-8"))
    nums = [p["n"] for p in spec["phrases"]]
    textes = {p["n"]: p["voix"] for p in spec["phrases"]}
    prises = [r for r in charger() if textes.get(r["n"]) == r["texte"]]     # prises d'un texte modifié depuis : ignorées
    for r in prises:
        r["defauts"] = controle(r)
    valides = [r for r in prises if not r["defauts"]]
    print(f"{len(prises)} prises, {len(valides)} sans défaut")
    if not valides:
        return
    for r in valides:
        r["intonation_fin"] = intonation_finale(r)
    cible = float(np.median([r["debit"] for r in valides])) * 0.95
    for r in prises:
        r["note"] = note(r, cible)
    # Réglage commun à tout l'épisode
    par_conf = defaultdict(dict)
    for r in valides:
        c = (r["ref"], "mix", "mix") if PAR_REF else (r["ref"], r["exag"], r["cfg"])
        if r["n"] not in par_conf[c] or r["note"] > par_conf[c][r["n"]]["note"]:
            par_conf[c][r["n"]] = r
    classement = sorted(par_conf.items(), key=lambda kv: (-len(kv[1]), -np.mean([x["note"] for x in kv[1].values()])))
    print("\nRéglages (phrases couvertes, note moyenne, UTMOS moyen, étendue moyenne, débit moyen) :")
    for c, d in classement[:8]:
        xs = list(d.values())
        ut = [x["utmos"] for x in xs if x.get("utmos") is not None]
        print(f"  {c}: {len(d)}/{len(nums)}  note {np.mean([x['note'] for x in xs]):+.2f}  "
              f"utmos {np.mean(ut) if ut else float('nan'):.2f}  étendue {np.mean([x['etendue_st'] for x in xs]):.2f} st  "
              f"débit {np.mean([x['debit'] for x in xs]):.1f}")
    if FORCE and PAR_REF:
        conf = (FORCE.split(",")[0], "mix", "mix")
    elif FORCE:
        ref, ex, cfg = FORCE.split(",")
        conf = (ref, float(ex), float(cfg))
    else:
        conf = classement[0][0]
    choix = par_conf[conf]
    # --forcer=12:2,13:4 : prise imposée (graine) pour une phrase, si elle est valable dans ce réglage
    forcer = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--forcer=")), "")
    for paire in filter(None, forcer.split(",")):
        # n:graine (réglage retenu) ou n:graine:référence (même exagération et cfg, autre référence)
        morceaux = paire.split(":")
        n_f, g_f = int(morceaux[0]), int(morceaux[1])
        ref_f = morceaux[2] if len(morceaux) > 2 else conf[0]
        if PAR_REF:   # n:graine:exagération (même référence que le réglage retenu)
            cand = [r for r in valides if r["n"] == n_f and r["graine"] == g_f and r["ref"] == conf[0]
                    and (len(morceaux) < 3 or abs(r["exag"] - float(morceaux[2])) < 1e-6)]
        else:
            cand = [r for r in valides if r["n"] == n_f and r["graine"] == g_f and (r["ref"], r["exag"], r["cfg"]) == (ref_f, conf[1], conf[2])]
        if cand:
            choix[n_f] = cand[0]
            print(f"  prise imposée pour s{n_f:02d} : graine {g_f}")
        else:
            print(f"  prise imposée pour s{n_f:02d} introuvable ou non valable")
    print(f"\nRéglage retenu : {conf}")
    manquantes = [n for n in nums if n not in choix]
    for n in nums:
        if n in choix:
            x = choix[n]
            print(f"  s{n:02d} ✓ {Path(x['fichier']).stem}  note {x['note']:+.2f}  étendue {x['etendue_st']}  "
                  f"débit {x['debit']}  fin {x.get('intonation_fin')} st  utmos {x.get('utmos')}  « {x['entendu']} »")
        else:
            cands = sorted([r for r in prises if r["n"] == n and (r["ref"] == conf[0] if PAR_REF else (r["ref"], r["exag"], r["cfg"]) == conf)],
                           key=lambda r: len(r["defauts"]))
            print(f"  s{n:02d} ✗ aucune prise valable : " + (" ; ".join(cands[0]["defauts"]) if cands else "pas de prise"))
            print(f"      texte   « {textes[n]} »")
            vus = set()
            for r in cands:                   # ce que Whisper a entendu : pour réécrire la phrase à coup sûr
                if r["entendu"] in vus:
                    continue
                vus.add(r["entendu"])
                faible = [f"{w['mot']} {w['proba']:.2f}" for w in r["mots"] if w.get("proba", 1) < 0.3]
                print(f"      entendu « {r['entendu']} »  [{' ; '.join(r['defauts'])}]" + (f"  faibles : {faible}" if faible else ""))
                if len(vus) >= 4:
                    break
    (EP / "voix_cb" / "choix.json").write_text(json.dumps(
        {"config": list(conf), "manquantes": manquantes,
         "choix": {str(n): Path(x["fichier"]).stem for n, x in choix.items()}}, ensure_ascii=False, indent=1))
    if ASSEMBLER and not manquantes:
        import soundfile as sf
        dest = EP / "voix" / "finale"
        dest.mkdir(parents=True, exist_ok=True)
        phrases = []
        for n in nums:
            x = choix[n]
            y, sr = sf.read(x["fichier"], dtype="float32")
            b = min(len(y), int((x["fin_voix"] + 0.12) * sr))
            y = y[:b].copy()
            fo = int(0.06 * sr)
            y[-fo:] *= np.linspace(1, 0, fo)
            # même niveau de voix d'une phrase à l'autre : RMS des passages parlés ramené à -20 dBFS
            hop = int(0.02 * sr)
            trames = np.array([np.sqrt(np.mean(y[i:i + hop] ** 2)) for i in range(0, len(y) - hop, hop)])
            parle = trames[trames > trames.max() * 10 ** (-30 / 20)]
            gain = 10 ** (-20 / 20) / max(float(np.sqrt(np.mean(parle ** 2))), 1e-6)
            y = y * min(gain, 0.97 / max(float(np.abs(y).max()), 1e-6))
            sf.write(dest / f"s{n:02d}.wav", y, sr, subtype="PCM_16")
            phrases.append({"n": n, "wer": x["wer"], "entendu": x["entendu"], "duree": round(len(y) / sr, 3),
                            "mots": [{k: w[k] for k in ("mot", "debut", "fin")} for w in x["mots"]],
                            "prise": Path(x["fichier"]).stem})
        (dest / "phrases.json").write_text(json.dumps(phrases, ensure_ascii=False, indent=1), encoding="utf-8")
        (dest / "bilan.json").write_text(json.dumps(
            {"moteur": "chatterbox", "config": list(conf), "wer_moyen": round(float(np.mean([p["wer"] for p in phrases])), 3),
             "duree_parole": round(sum(p["duree"] for p in phrases), 1)}, ensure_ascii=False, indent=1))
        print(f"\nassemblé dans {dest} ({sum(p['duree'] for p in phrases):.1f} s de parole)")


if __name__ == "__main__":
    main()
