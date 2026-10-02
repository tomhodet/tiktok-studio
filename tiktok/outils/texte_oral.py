"""Comparaison d'un texte écrit et de ce que Whisper en a retranscrit, à l'oreille : deux mots sont
« les mêmes » s'ils se prononcent pareil (homophones, terminaisons muettes, accents, élisions avalées,
nombres en chiffres). Partagé par choisir_voix.py (tri des prises) et verif_voix.py (vérification finale).
"""
import re
import unicodedata

HOMOPHONES = [{"ses", "ces", "c'est", "s'est", "sait"}, {"a", "à", "as"}, {"et", "est", "es"}, {"ou", "où"},
              {"on", "ont"}, {"son", "sont"}, {"mais", "mes", "met", "mets"}, {"peu", "peut", "peux"},
              {"la", "là", "l'a"}, {"quand", "qu'en", "quant"}, {"leur", "leurs"}, {"ce", "se"}, {"ma", "m'a"},
              {"ta", "t'a"}, {"sa", "ça"}, {"dit", "dis"}, {"fait", "fais"}, {"vie", "vit"}, {"fin", "faim"},
              {"pere", "père", "paire"}, {"par", "pars", "part"}, {"mère", "mer", "maire"}, {"cœur", "choeur", "chœur"},
              {"ceux", "ce"}, {"traitera", "traîtra", "traitra"}, {"prends", "prend"},
              {"pousse", "pouce", "pousses", "pouces"}, {"cou", "coup", "coût", "coups"}, {"verre", "vers", "vert", "ver"},
              {"sans", "sang", "cent", "s'en"}, {"tant", "temps", "t'en", "tend", "tends"}, {"voix", "voie", "vois", "voit"},
              {"courrait", "courait"}, {"mourrait", "mourait"}, {"mile", "mille", "miles"},
              {"les", "l'ai", "lait", "laie"}, {"il", "ils"}, {"elle", "elles"}, {"des", "dès"}, {"du", "dû"},
              {"sur", "sûr"}, {"si", "s'y", "scie"}, {"ni", "n'y", "nid"}, {"qu'il", "qu'ils"}]
GROUPE = {m: sorted(g)[0] for g in HOMOPHONES for m in g}
ELISIONS = ("n'", "l'", "d'")       # « on n'apprend », « toute l'usine » : avalées à l'oral ou oubliées par Whisper


def nombres_en_lettres(t: str) -> str:
    """« 80 » (transcription) = « quatre-vingts » (texte), « 101e » = « cent unième », « 1m80 »."""
    try:
        from num2words import num2words
    except ImportError:
        return t
    t = re.sub(r"(\d{1,2})\s*h\s*(\d{2})\b", r"\1 heures \2", t)      # « 6h12 » = six heures douze
    t = re.sub(r"(\d{1,2})\s*h\b", r"\1 heures", t)
    t = re.sub(r"(\d)\s*m\s*(\d{2})\b", r"\1 mètre \2", t)             # « 1m80 » = un mètre quatre-vingts
    t = re.sub(r"(?<=\d)[\s  .](?=\d{3}\b)", "", t)          # « 10 000 » = dix mille
    t = re.sub(r"\b(\d+)\s*(?:ères?|ers?|èmes?|emes?|es?)\b",
               lambda m: " " + num2words(int(m.group(1)), lang="fr", to="ordinal") + " ", t)
    return re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="fr") + " ", t)


def norm(t: str) -> list[str]:
    t = unicodedata.normalize("NFC", nombres_en_lettres(t).lower()).replace("’", "'").replace("*", "")
    t = re.sub(r"\s+'", "'", t)      # la transcription détache parfois « j » de « 'avais »
    return re.sub(r"[^\w' ]+", " ", t).split()


def canon(m: str) -> str:
    """Forme de comparaison : même forme pour deux mots qui se prononcent pareil."""
    m = GROUPE.get(m, m)
    for e in ELISIONS:
        if m.startswith(e) and len(m) > 3:
            m = GROUPE.get(m[2:], m[2:])
    m = "".join(c for c in unicodedata.normalize("NFD", m) if not unicodedata.combining(c))
    if len(m) > 3:
        # finales en [e] : plané = planait = planer = planez, piqué = piquet
        m = re.sub(r"(aient|ais|ait|ai|ez|er|et)$", "e", m)
        # ils demandent = il demande
        if m.endswith("ent") and len(m) > 4:
            m = m[:-2]
    # lettres finales muettes : serais = serai, questions = question, grandit = grandi, aimée = aimé
    return m.rstrip("stex") if len(m.rstrip("stex")) >= 2 else m


def mots_proches(a: str, b: str) -> bool:
    return a == b or canon(a) == canon(b)
