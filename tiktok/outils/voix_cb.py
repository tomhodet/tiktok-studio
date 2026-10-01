"""Voix Chatterbox (multilingue, licence MIT) : plusieurs prises par phrase, chacune contrôlée.

  python voix_cb.py <nom_tache> <lot>

La tâche est décrite dans tiktok/voix_cb.json :
  {"taches": [{"nom": "mere1_r1", "episode": "tiktok/mere1", "phrases": "toutes" ou [1, 4],
               "refs": ["mere_A"], "exag": [0.5, 0.8], "cfg": [0.3, 0.5], "graines": [1],
               "lots": 4, "whisper": "medium"}]}
Chaque combinaison (phrase, référence, exagération, cfg, graine) donne une prise ; le lot k traite
les combinaisons d'indice i tel que i % lots == k.

Sortie : <episode>/voix_cb/<nom_tache>/sNN__<ref>_e<ex>_c<cfg>_g<graine>.flac et .json (mesures) :
transcription Whisper, taux d'erreur, mots (horodatage, probabilité), premier et dernier mot bien dits,
fin brusque du modèle, courbe de hauteur, débit, note de naturel (UTMOS) si disponible.

Découpe douce : seuls les silences de tête et de queue sont retirés, avec des marges et des fondus,
pour ne jamais couper un mot. Aucun changement de tempo.
"""
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

NOM, LOT = sys.argv[1], int(sys.argv[2])
SPEC = json.loads(Path("tiktok/voix_cb.json").read_text(encoding="utf-8"))
TACHE = next(t for t in SPEC["taches"] if t["nom"] == NOM)
EP = Path(TACHE["episode"])
SORTIE = EP / "voix_cb" / NOM
REFS = Path("tiktok/voix_ref/refs")


def normaliser(t: str) -> list[str]:
    t = unicodedata.normalize("NFC", t.lower()).replace("’", "'").replace("*", "")
    t = re.sub(r"[^\w' ]+", " ", t)
    return t.split()


def wer(ref: str, hyp: str) -> float:
    r, h = normaliser(ref), normaliser(hyp)
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return d[len(h)] / max(len(r), 1)


def dernier_mot(t: str) -> str:
    m = normaliser(t)
    return m[-1].split("'")[-1] if m else ""


def premier_mot(t: str) -> str:
    m = normaliser(t)
    return m[0].split("'")[0] if m else ""


def main() -> None:
    import librosa
    import soundfile as sf
    import torch

    _charge = torch.load

    def charge_cpu(*a, **k):
        k.setdefault("map_location", torch.device("cpu"))
        return _charge(*a, **k)

    torch.load = charge_cpu
    torch.set_num_threads(os.cpu_count() or 4)
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    from faster_whisper import WhisperModel

    spec = json.loads((EP / "script.json").read_text(encoding="utf-8"))
    phrases = {p["n"]: p for p in spec["phrases"]}
    choix = sorted(phrases) if TACHE["phrases"] == "toutes" else TACHE["phrases"]
    combos = [(n, r, e, c, g) for n in choix for r in TACHE["refs"] for e in TACHE["exag"]
              for c in TACHE["cfg"] for g in TACHE["graines"]]
    mes = [x for i, x in enumerate(combos) if i % TACHE["lots"] == LOT]
    mes.sort(key=lambda x: (x[1], x[2]))          # une préparation de référence par groupe
    SORTIE.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    modele = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
    sr = modele.sr
    whisper = WhisperModel(TACHE.get("whisper", "medium"), device="cpu", compute_type="int8")
    utmos = None
    try:
        utmos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True)
    except Exception as e:  # la note de naturel est un plus, pas une condition
        print("UTMOS indisponible :", repr(e), flush=True)
    print(f"modèles chargés en {time.time() - t0:.0f} s, {len(mes)} prises", flush=True)

    ref_courante = None
    for n, ref, ex, cfg, g in mes:
        nom = f"s{n:02d}__{ref}_e{ex}_c{cfg}_g{g}"
        if (SORTIE / f"{nom}.json").exists():
            continue
        texte = phrases[n]["voix"]
        t1 = time.time()
        if ref != ref_courante:
            modele.prepare_conditionals(str(REFS / f"{ref}.wav"), exaggeration=ex)
            ref_courante = ref
        torch.manual_seed(1000 * g + n)
        wav = modele.generate(texte, language_id="fr", exaggeration=ex, cfg_weight=cfg)
        brut = wav.squeeze().cpu().numpy().astype(np.float32)
        # Fin brusque : le modèle s'arrête en plein son
        q = int(0.03 * sr)
        rms_fin = float(np.sqrt(np.mean(brut[-q:] ** 2)) + 1e-9)
        rms_max = float(np.max(librosa.feature.rms(y=brut, frame_length=1024, hop_length=256)) + 1e-9)
        fin_brusque = 20 * np.log10(rms_fin / rms_max) > -28
        # Découpe douce : marges de 120 ms en tête et 250 ms en queue, fondus
        iv = librosa.effects.split(brut, top_db=50, frame_length=1024, hop_length=256)
        a = max(0, int(iv[0][0] - 0.12 * sr)) if len(iv) else 0
        b = min(len(brut), int(iv[-1][1] + 0.25 * sr)) if len(iv) else len(brut)
        y = brut[a:b].copy()
        fi, fo = int(0.01 * sr), int(0.04 * sr)
        if len(y) > fi + fo:
            y[:fi] *= np.linspace(0, 1, fi)
            y[-fo:] *= np.linspace(1, 0, fo)
        y = y * (0.89 / max(float(np.abs(y).max()), 1e-6))
        sf.write(SORTIE / f"{nom}.flac", y, sr)
        t2 = time.time()
        # Contrôle par transcription
        y16 = librosa.resample(y, orig_sr=sr, target_sr=16000)
        segs, _ = whisper.transcribe(y16, language="fr", beam_size=5, word_timestamps=True,
                                     condition_on_previous_text=False)
        segs = list(segs)
        entendu = " ".join(s.text.strip() for s in segs)
        mots = [{"mot": w.word.strip(), "debut": round(w.start, 3), "fin": round(w.end, 3),
                 "proba": round(w.probability, 3)} for s in segs for w in (s.words or [])]
        duree = len(y) / sr
        fin_marge = round(duree - mots[-1]["fin"], 3) if mots else 0.0
        # Hauteur et débit
        f0, voise, _ = librosa.pyin(y16, fmin=60, fmax=450, sr=16000, frame_length=1024, hop_length=160)
        f0v = f0[voise]
        etendue = float(np.std(12 * np.log2(f0v / np.median(f0v)))) if len(f0v) > 20 else 0.0
        parole = (mots[-1]["fin"] - mots[0]["debut"]) if len(mots) > 1 else duree
        lettres = sum(ch.isalpha() for ch in texte)
        note = None
        if utmos is not None:
            try:
                note = round(float(utmos(torch.from_numpy(y16).unsqueeze(0), 16000).item()), 3)
            except Exception:
                note = None
        r = {"nom": nom, "n": n, "ref": ref, "exag": ex, "cfg": cfg, "graine": g, "texte": texte,
             "entendu": entendu, "wer": round(wer(texte, entendu), 3),
             "debut_ok": premier_mot(entendu) == premier_mot(texte),
             "fin_ok": dernier_mot(entendu) == dernier_mot(texte),
             "fin_brusque": bool(fin_brusque), "fin_marge": fin_marge,
             "proba_min": min((m["proba"] for m in mots), default=0.0),
             "duree": round(duree, 2), "debit": round(lettres / max(parole, 0.5), 2),
             "f0_mediane": round(float(np.median(f0v)), 1) if len(f0v) else None,
             "etendue_st": round(etendue, 2), "utmos": note, "mots": mots,
             "calcul_s": round(t2 - t1, 1)}
        (SORTIE / f"{nom}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{nom}: wer {r['wer']} fin_ok {r['fin_ok']} brusque {r['fin_brusque']} "
              f"étendue {r['etendue_st']} débit {r['debit']} utmos {note} ({r['calcul_s']} s) « {entendu} »",
              flush=True)


if __name__ == "__main__":
    main()
