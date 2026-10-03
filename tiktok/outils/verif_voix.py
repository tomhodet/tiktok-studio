"""Vérification finale d'un épisode monté : la piste de voix complète est retranscrite d'un bout à
l'autre, et chaque phrase du script doit s'y retrouver entière, dans l'ordre, sans mot coupé.

  python verif_voix.py <episode>        (GitHub Actions : Whisper « medium »)
Entrée : <episode>/verif/voix_montee.flac et verif/chrono.json (début et fin de chaque phrase).
Sortie : <episode>/verif/rapport.json
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from texte_oral import canon, noms_propres, norm  # noqa: E402

EP = Path(sys.argv[1])


def main() -> None:
    import librosa
    from faster_whisper import WhisperModel
    chrono = json.loads((EP / "verif" / "chrono.json").read_text(encoding="utf-8"))
    y, _ = librosa.load(str(EP / "verif" / "voix_montee.flac"), sr=16000)
    modele = WhisperModel("medium", device="cpu", compute_type="int8")
    # Chaque phrase est découpée dans le son final (avec 0,3 s de marge) et transcrite seule :
    # on vérifie exactement ce que le spectateur entend, phrase par phrase, musique comprise.
    par_phrase = {}
    for c in chrono:
        a, b = max(0, int((c["debut"] - 0.3) * 16000)), int((c["fin"] + 0.3) * 16000)
        segs, _ = modele.transcribe(y[a:b], language="fr", beam_size=5, word_timestamps=True,
                                    condition_on_previous_text=False, vad_filter=False)
        par_phrase[c["n"]] = [{"mot": w.word.strip(), "proba": w.probability} for s in segs for w in (s.words or [])]
    rapport, ok = [], True
    for c in chrono:
        dans = par_phrase[c["n"]]
        attendu = [canon(m) for m in norm(c["texte"])]
        entendu = [canon(m) for m in norm(" ".join(m["mot"] for m in dans))]
        import difflib
        sm = difflib.SequenceMatcher(None, attendu, entendu, autojunk=False)
        # nom propre remplacé un pour un (Karikó entendu Carrico) : toléré
        noms = {canon(m) for m in noms_propres(c["texte"])}
        ops = [o for o in sm.get_opcodes() if not (o[0] == "replace" and o[2] - o[1] == o[4] - o[3]
                                                   and all(attendu[i] in noms for i in range(o[1], o[2])))]
        manquants = [attendu[i] for op, i1, i2, _, _ in ops if op in ("delete", "replace") for i in range(i1, i2)]
        en_trop = [entendu[j] for op, _, _, j1, j2 in ops if op in ("insert", "replace") for j in range(j1, j2)]
        faibles = [m["mot"] for m in dans if m["proba"] < 0.3 and re.search(r"\w", m["mot"])]
        bon = not manquants and not en_trop
        ok &= bon
        rapport.append({"n": c["n"], "ok": bon, "attendu": c["texte"], "entendu": re.sub(r"\s+'", "'", " ".join(m["mot"] for m in dans)),
                        "manquants": manquants, "en_trop": en_trop, "douteux": faibles})
        print(("OK " if bon else "!! ") + f"s{c['n']:02d} « {' '.join(m['mot'] for m in dans)} »"
              + (f"  manquants {manquants} en trop {en_trop}" if not bon else ""), flush=True)
    (EP / "verif" / "rapport.json").write_text(json.dumps({"ok": ok, "phrases": rapport}, ensure_ascii=False,
                                                          indent=1), encoding="utf-8")
    print("VERDICT :", "tout est dit, rien n'est coupé" if ok else "à reprendre", flush=True)


if __name__ == "__main__":
    main()
