"""Vérification finale d'un épisode monté : la piste de voix complète est retranscrite d'un bout à
l'autre, et chaque phrase du script doit s'y retrouver entière, dans l'ordre, sans mot coupé.

  python verif_voix.py <episode>        (GitHub Actions : Whisper « medium »)
Entrée : <episode>/verif/voix_montee.flac et verif/chrono.json (début et fin de chaque phrase).
Sortie : <episode>/verif/rapport.json
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

EP = Path(sys.argv[1])


def nombres_en_lettres(t: str) -> str:
    """« 80 » (transcription) = « quatre-vingts » (texte)."""
    try:
        from num2words import num2words
    except ImportError:
        return t
    return re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="fr") + " ", t)


HOMOPHONES = [{"ses", "ces", "c'est", "s'est", "sait"}, {"a", "à", "as"}, {"et", "est", "es"}, {"ou", "où"},
              {"on", "ont"}, {"son", "sont"}, {"mais", "mes", "met", "mets"}, {"peu", "peut", "peux"},
              {"la", "là", "l'a"}, {"quand", "qu'en", "quant"}, {"leur", "leurs"}, {"ce", "se"}, {"ma", "m'a"},
              {"ta", "t'a"}, {"sa", "ça"}, {"dit", "dis"}, {"fait", "fais"}, {"vie", "vit"}, {"fin", "faim"},
              {"pere", "père", "paire"}, {"par", "pars", "part"}, {"mère", "mer", "maire"}, {"cœur", "choeur", "chœur"},
              {"ceux", "ce"}, {"traitera", "traîtra", "traitra"}, {"prends", "prend"},
              {"pousse", "pouce", "pousses", "pouces"}, {"cou", "coup", "coût", "coups"}, {"verre", "vers", "vert", "ver"},
              {"sans", "sang", "cent", "s'en"}, {"tant", "temps", "t'en"}, {"voix", "voie", "vois", "voit"}]


def canon(m: str) -> str:
    """Forme de comparaison : sans accents, homophones ramenés à une seule forme (même son, autre orthographe)."""
    if m.startswith("n'") and len(m) > 3:     # « on n'apprend » = « on apprend » à l'oreille (liaison)
        m = m[2:]
    for g in HOMOPHONES:
        if m in g:
            m = sorted(g)[0]
            break
    m = "".join(c for c in unicodedata.normalize("NFD", m) if not unicodedata.combining(c))
    # terminaisons muettes : serai = serais, question = questions, ils demandent = il demande
    if m.endswith("ent") and len(m) > 4:
        m = m[:-2]
    return m.rstrip("stex") if len(m.rstrip("stex")) >= 2 else m


def norm(t: str) -> list[str]:
    t = unicodedata.normalize("NFC", nombres_en_lettres(t).lower()).replace("’", "'").replace("*", "")
    t = re.sub(r"\s+'", "'", t)      # la transcription détache « j » de « 'avais »
    return re.sub(r"[^\w' ]+", " ", t).split()


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
        manquants = [attendu[i] for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace")
                     for i in range(i1, i2)]
        en_trop = [entendu[j] for op, _, _, j1, j2 in sm.get_opcodes() if op in ("insert", "replace")
                   for j in range(j1, j2)]
        faibles = [m["mot"] for m in dans if m["proba"] < 0.3]
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
