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
              {"sur", "sûr"}, {"j'ai", "j'aie", "j'aies"}, {"si", "s'y", "scie"}, {"ni", "n'y", "nid"}, {"qu'il", "qu'ils"}]
GROUPE = {m: sorted(g)[0] for g in HOMOPHONES for m in g}
ELISIONS = ("n'", "l'", "d'")       # « on n'apprend », « toute l'usine » : avalées à l'oral ou oubliées par Whisper


ROMAINS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def romain(s: str) -> int:
    """« XIV » = 14."""
    total = 0
    for k, c in enumerate(s):
        v = ROMAINS[c]
        total += -v if k + 1 < len(s) and ROMAINS[s[k + 1]] > v else v
    return total


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
    t = re.sub(r"(\d+)\s*%", r"\1 pour cent", t)
    t = re.sub(r"\b[IVXLC]{2,}\b", lambda m: str(romain(m.group())), t)          # Louis XIV
    t = re.sub(r"\b(\d+)\s*(?:ères?|ers?|èmes?|emes?|es?)\b",
               lambda m: " " + num2words(int(m.group(1)), lang="fr", to="ordinal") + " ", t)
    return re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="fr") + " ", t)


def norm(t: str) -> list[str]:
    t = unicodedata.normalize("NFC", nombres_en_lettres(t).lower()).replace("’", "'").replace("*", "")
    t = re.sub(r"\s+'", "'", t)      # la transcription détache parfois « j » de « 'avais »
    return re.sub(r"[^\w' ]+", " ", t).split()


def ecrit(m: str) -> str:
    """Forme écrite normalisée : homophones, élisions, accents, finales muettes."""
    m = GROUPE.get(m, m)
    for e in ELISIONS:
        if m.startswith(e) and len(m) > 3:
            m = GROUPE.get(m[2:], m[2:])
    m = "".join(c for c in unicodedata.normalize("NFD", m) if not unicodedata.combining(c))
    m = re.sub(r"[sx]$", "", m) if len(m) > 3 else m
    if len(m) > 3:
        # finales en [e] : plané = planait = planer = planez, piqué = piquet
        m = re.sub(r"(aien|aient|ais|ait|ai|ez|er|et)$", "e", m)
        # ils demandent = il demande
        if m.endswith("ent") and not m.endswith("ient") and len(m) > 4:      # devient = deviens
            m = m[:-2]
    # lettres finales muettes : dettes = dette, grandit = grandi, aimée = aimé, mord = mort
    for motif in (r"[sx]$", r"e+$" if re.search(r"e+$", re.sub(r"[sx]$", "", m)) else r"[tdp]$"):
        court = re.sub(motif, "", m)
        if len(court) >= 2:
            m = court
    return m


def canon(m: str) -> str:
    """Forme de comparaison : même forme pour deux mots qui se prononcent pareil (orthographe des noms propres
    comprise : Dahl = Dall, Lauda = Loda, Johnny = Jonny, Goddard = Godard)."""
    m = ecrit(m)
    for a, b in (("x", "ks"), ("ph", "f"), ("sch", "ʃ"), ("ch", "ʃ"), ("sh", "ʃ"), ("ck", "k"), ("qu", "k"),
                 ("q", "k"), ("w", "v"), ("y", "i"), ("z", "s"), ("h", ""), ("eau", "o"), ("au", "o"),
                 ("ai", "e"), ("ei", "e"), ("oe", "e")):
        m = m.replace(a, b)
    m = re.sub(r"c(?=[eiy])", "s", m)
    m = re.sub(r"g(?=[eiy])", "j", m)
    m = m.replace("gu", "g").replace("c", "k")
    m = re.sub(r"(.)\1+", r"\1", m)
    m = re.sub(r"v$", "f", m)
    m = re.sub(r"m$", "n", m)
    return m or "?"


def noms_propres(texte: str) -> set[str]:
    """Mots du texte écrits avec une majuscule hors début de phrase (Karikó, Semmelweis, Lille, un J) :
    Whisper les orthographie souvent autrement, la voix les dit pourtant bien. Leur substitution un pour un
    est tolérée."""
    noms = set()
    for m in re.finditer(r"(?<![.!?:]\s)(?<!^)\b([A-ZÀ-Ý][\w'-]*)", texte.replace("*", "").strip()):
        noms.update(norm(m.group(1)))
    return noms


def mots_proches(a: str, b: str, noms: set[str] = frozenset()) -> bool:
    return a == b or canon(a) == canon(b) or a in noms
