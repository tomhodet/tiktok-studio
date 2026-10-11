"""Montage « nouveau format » : plein écran 9:16, un plan vidéo par phrase (banque Pexels ou plans fournis),
zoom lent, étalonnage cinéma, sous-titres mot à mot au centre, accroche en grand dès la première seconde,
musique composée. Aucun bandeau de série, aucun numéro d'épisode.

  python3 montage2.py <episode> <plan.json> <sortie.mp4>
<episode>/script.json et <episode>/voix/finale/{sNN.wav, phrases.json} doivent exister.
plan.json : {"style": "intime" | "coach", "plans": [{"q": "requête banque"} | {"fichier": "x.mp4", "debut": 12.0}, ...]}
  un plan par phrase (le dernier est réutilisé s'il en manque).
"""
import json
import math
import random
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ICI = Path(__file__).parent
EP, PLAN, SORTIE = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
TRAV = EP / "_travail2"
COUPE_MAX = 3.4          # au-delà, la phrase reçoit deux plans
CACHE = Path.home() / "cache_pexels"
BANQUE = Path("tiktok/banque/index.json")
FONTS = ICI.parent.parent / "templates" / "fonts"
W, H, FPS = 1080, 1920, 30
DEBUT = 0.12            # la voix démarre tout de suite
QUEUE = 1.3             # après la dernière phrase
TRANS = 0.32            # durée des transitions entre plans
TRANSITIONS = ["zoomin", "smoothleft", "hblur", "smoothup", "circleopen", "slideleft", "fadewhite", "smoothright",
               "radial", "smoothdown", "wipeleft", "dissolve"]
OR = "&H3CC8FF&"        # doré (BGR)
BLANC = "&HFFFFFF&"
GRIS = "&HC8C8C8&"


def ff(*args, **kw):
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-y", *map(str, args)]
    subprocess.run(cmd, check=True, **kw)


def duree_fichier(f: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


# ─────────────────────────── plans ───────────────────────────
def candidats(q: str, deja: set, graine: int) -> list[dict]:
    index = json.loads(BANQUE.read_text(encoding="utf-8"))
    if q.isdigit():                   # plan choisi à la main sur la planche : son numéro Pexels
        return [index[q]] if q in index and isinstance(index[q], dict) else []
    cands = [v for v in index.values() if isinstance(v, dict) and v.get("q") == q and v["id"] not in deja]
    if not cands:
        cands = [v for v in index.values() if isinstance(v, dict) and q.split()[0] in v.get("q", "") and v["id"] not in deja]
    if not cands:
        raise SystemExit(f"aucun plan en banque pour « {q} »")
    cands.sort(key=lambda v: (not (v.get("hauteur", 0) > v.get("largeur", 1)),
                              max(v.get("largeur", 0), v.get("hauteur", 0)) < 3840,
                              v.get("lum", 60) < 70, -v.get("note", 0)))
    tete = cands[:4]
    random.Random(graine).shuffle(tete)
    return tete + cands[4:]


def luminance(f: Path) -> float:
    """Luminance moyenne (0-255) de trois images du segment : un plan noir est écarté."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-vf", "select='not(mod(n\,20))',scale=16:9,format=gray",
                          "-frames:v", "4", "-f", "rawvideo", "-"], capture_output=True).stdout
    return float(np.frombuffer(out, dtype=np.uint8).mean()) if out else 0.0


def telecharger(clip: dict) -> Path:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{clip['id']}.mp4"
    deja_uhd = CACHE / f"{clip['id']}.uhd"          # téléchargement 4K déjà tenté
    if f.exists() and f.stat().st_size > 100_000 and (deja_uhd.exists() or cote_min(f) >= 1400):
        return f
    i, fps = clip["id"], clip["fichier"].get("fps", 25)
    lg, ht = clip.get("largeur", 0), clip.get("hauteur", 0)
    portrait = ht > lg
    urls = []
    dims = [f"{lg}_{ht}"] if min(lg, ht) >= 1440 else []
    dims += ["2160_3840", "1440_2560"] if portrait else ["3840_2160", "2560_1440"]
    for d in dims:
        for fr in {f"{int(round(fps))}fps", f"{fps:g}fps"}:
            urls.append(f"https://videos.pexels.com/video-files/{i}/{i}-uhd_{d}_{fr}.mp4")
    deja_uhd.touch()
    if f.exists() and f.stat().st_size > 100_000:
        urls = urls          # version HD en cache : on tente seulement la 4K
    else:
        urls.append(clip["fichier"]["lien"])
    tmp = f.with_suffix(".part")
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(tmp, "wb") as o:
                shutil.copyfileobj(r, o)
            tmp.replace(f)
            return f
        except Exception:
            continue
    if f.exists() and f.stat().st_size > 100_000:
        return f
    raise RuntimeError(f"plan {i} introuvable")


def cote_min(f: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.strip().split(",")
    try:
        return min(int(out[0]), int(out[1]))
    except (ValueError, IndexError):
        return 0


def segment(src: Path, debut: float, duree: float, k: int, style: str, sortie: Path, x: float = 0.5) -> None:
    """Plan recadré plein écran avec zoom lent (alterné avant / arrière), étalonné."""
    dispo = duree_fichier(src)
    if debut + duree > dispo - 0.1:
        debut = max(0.0, dispo - duree - 0.1)
    if k == 0:                        # ouverture : recul rapide, effet « coup de poing »
        z0, z1 = 1.22, 1.04
    else:
        z0, z1 = (1.02, 1.12) if k % 2 == 0 else (1.13, 1.03)
    pente = (z1 - z0) / max(duree, 0.1)
    zoom = f"({z0}+{pente:.5f}*t)/1.25"
    grade = ("eq=contrast=1.08:saturation=0.88:brightness=0.02:gamma=1.04,vignette=PI/5.5,unsharp=5:5:0.55"
             if style == "intime" else
             "eq=contrast=1.16:saturation=0.95:brightness=0.01:gamma=1.02,vignette=PI/5,unsharp=5:5:0.65")
    vf = (f"trim=start={debut:.3f}:duration={duree + 0.1:.3f},setpts=PTS-STARTPTS,fps={FPS},"
          # réduction de qualité une seule fois (4K -> 1,25 x l'écran), puis zoom par réduction : image nette
          f"scale=w='ceil(iw*max({H}/ih\\,{W}/iw)*1.25/2)*2':h=-2:flags=lanczos,"
          f"scale=w='ceil(iw*{zoom}/2)*2':h=-2:eval=frame:flags=bicubic,"
          f"crop={W}:{H}:x='(iw-{W})*{x:.3f}',setsar=1,{grade},format=yuv420p,trim=duration={duree:.3f}")
    ff("-i", src, "-an", "-vf", vf, "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", sortie)


def plan_lumineux(q: str, deja: set, graine: int, duree: float, k: int, style: str, seg: Path, debut: float) -> None:
    """Premier plan de la banque pour « q » qui se télécharge et n'est pas trop sombre."""
    for clip in candidats(q, deja, graine):
        try:
            src = telecharger(clip)
        except Exception as e:
            print(f"  plan {k + 1}: {clip['id']} injoignable ({e})", flush=True)
            continue
        if cote_min(src) < 1080:
            print(f"  plan {k + 1}: {clip['id']} trop petit, autre plan", flush=True)
            continue
        segment(src, debut, duree, k, style, seg)
        lum = luminance(seg)
        if lum >= 40:
            deja.add(clip["id"])
            print(f"  plan {k + 1}: {clip['id']} « {clip['q']} » ({clip['auteur']}), {cote_min(src)}p, lum {lum:.0f}",
                  flush=True)
            return
        print(f"  plan {k + 1}: {clip['id']} trop sombre (lum {lum:.0f}), autre plan", flush=True)
    raise SystemExit(f"aucun plan assez lumineux pour « {q} »")


# ─────────────────────────── bruitages ───────────────────────────
def fabriquer_bruitages(instants: list[float], total: float, style: str, sortie: Path) -> None:
    """Souffle filtré (whoosh) à chaque transition et impact grave à l'ouverture, synthétisés (aucun échantillon)."""
    sr = 48000
    piste = np.zeros(int((total + 1) * sr), dtype="float32")
    rng = np.random.default_rng(3)
    niveau = 0.16 if style == "coach" else 0.09

    def poser(son, t0):
        a = int(max(0, t0) * sr)
        b = min(len(piste), a + len(son))
        piste[a:b] += son[:b - a]
    # whoosh : bruit rose, filtre passe-bande qui monte, enveloppe en cloche
    n = int(0.55 * sr)
    for t0 in instants:
        blanc = rng.standard_normal(n).astype("float32")
        rose = np.cumsum(blanc)
        rose -= np.convolve(rose, np.ones(400) / 400, mode="same")
        rose /= np.abs(rose).max() + 1e-9
        x = np.linspace(0, 1, n)
        env = np.sin(np.pi * x) ** 2 * (0.4 + 0.6 * x)
        # balayage : mélange progressif vers les aigus
        aigu = np.diff(rose, prepend=0)
        aigu /= np.abs(aigu).max() + 1e-9
        son = (rose * (1 - x) + aigu * x) * env * niveau
        poser(son.astype("float32"), t0 - 0.3)
    # impact d'ouverture : sinus grave qui descend, très court
    n = int(0.9 * sr)
    x = np.arange(n) / sr
    f = 70 * np.exp(-x * 2.5) + 38
    boum = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-x * 5) * (0.55 if style == "coach" else 0.35)
    poser(boum.astype("float32"), 0.0)
    sf.write(sortie, piste[:int(total * sr)], sr)


# ─────────────────────────── sous-titres ───────────────────────────
def mots_script(mots_whisper: list[dict], affiche: str) -> list[dict]:
    """Les mots du script (orthographe sûre, nombres en lettres), calés sur les horaires de Whisper par
    position dans le texte : le k-ième caractère parlé tombe au même instant dans les deux textes."""
    ws = [dict(w) for w in mots_whisper]
    # jetons d'apostrophe détachés (« n », « 'avais ») recollés
    fusion = []
    for w in ws:
        if fusion and (w["mot"].startswith("'") or fusion[-1]["mot"].endswith("'")):
            fusion[-1]["mot"] += w["mot"]
            fusion[-1]["fin"] = w["fin"]
        else:
            fusion.append(w)
    ws = fusion
    total_w = sum(len(re.sub(r"[^\w]", "", w["mot"])) for w in ws) or 1
    # courbe caractère -> temps
    points, c = [], 0
    for w in ws:
        n = len(re.sub(r"[^\w]", "", w["mot"]))
        points.append((c / total_w, w["debut"]))
        c += n
        points.append((c / total_w, w["fin"]))

    def temps(frac: float) -> float:
        for (fa, ta), (fb, tb) in zip(points, points[1:]):
            if fa <= frac <= fb:
                return ta + (tb - ta) * ((frac - fa) / (fb - fa) if fb > fa else 0)
        return points[-1][1]
    jetons = affiche.split()
    total_s = sum(len(re.sub(r"[^\w]", "", j)) for j in jetons) or 1
    res, c = [], 0
    for j in jetons:
        n = len(re.sub(r"[^\w]", "", j))
        d, f = temps(c / total_s), temps((c + n) / total_s)
        res.append({"mot": j.replace("*", ""), "debut": d, "fin": max(f, d + 0.05), "fort": "*" in j})
        c += n
    return res


def groupes(mots: list[dict], affiche: str) -> list[list[dict]]:
    """Groupes de 2 à 4 mots, coupés à la ponctuation. Les mots forts (*mot*) sont repérés sur le texte affiché."""
    mots = mots_script(mots, affiche)
    res, cur = [], []
    for m in mots:
        cur.append(m)
        fin_phrase = re.search(r"[.!?:;]$", m["mot"]) is not None      # jamais deux phrases dans le même groupe
        virgule = m["mot"].endswith(",")
        if len(cur) >= 4 or fin_phrase or (virgule and len(cur) >= 2):
            res.append(cur)
            cur = []
    if cur:
        if res and len(cur) == 1 and len(res[-1]) < 4 and not re.search(r"[.!?:;]$", res[-1][-1]["mot"]):
            res[-1].extend(cur)
        else:
            res.append(cur)
    return res


def ass_temps(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def echapper(t: str) -> str:
    return t.replace("\\", "").replace("{", "(").replace("}", ")")


def couper_lignes(texte: str, maxi: int) -> str:
    """Retours à la ligne équilibrés (\\N) pour le cartouche d'accroche."""
    mots = texte.split()
    n = max(1, -(-len(texte) // maxi))
    cible = len(texte) / n
    lignes, cur = [], ""
    for m in mots:
        if cur and len(cur) + 1 + len(m) > cible + 4 and len(lignes) < n - 1:
            lignes.append(cur)
            cur = m
        else:
            cur = f"{cur} {m}".strip()
    lignes.append(cur)
    return "\\N".join(lignes)


def ecrire_ass(chrono: list[dict], fin_texte: str, total: float, style: str, chemin: Path, titre: str = "") -> None:
    taille_sub, taille_hook = (76, 100) if style == "intime" else (80, 104)
    entete = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Montserrat,{taille_sub},{BLANC},{BLANC},&H000000&,&H80000000&,1,0,0,0,100,100,0.5,0,1,3.2,1.5,5,70,70,0,1
Style: Hook,Montserrat,{taille_hook},{BLANC},{BLANC},&H000000&,&H80000000&,1,0,0,0,100,100,0.8,0,1,3.6,2,5,60,60,0,1
Style: Fin,Montserrat,72,&H101010&,&H101010&,&H3CC8FF&,&H3CC8FF&,1,0,0,0,100,100,0.5,0,3,16,0,2,90,90,430,1
Style: Choc,Montserrat,150,{OR},{OR},&H101010&,&H90000000&,1,0,0,0,100,100,2,0,1,5,4,5,40,40,0,1
Style: Titre,Montserrat,76,&H101010&,&H101010&,&HFFFFFF&,&HFFFFFF&,1,0,0,0,100,100,0.5,0,3,18,0,5,90,90,0,1
Style: Barre,Montserrat,10,{OR},{OR},&H000000&,&H000000&,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lignes = []
    for i, c in enumerate(chrono):
        st = "Hook" if i == 0 else "Sub"
        gs = groupes(c["mots"], c["affiche"])
        for gi, g in enumerate(gs):
            fin_groupe = g[-1]["fin"] + c["debut"] + 0.3
            suivant = c["debut"] + gs[gi + 1][0]["debut"] if gi + 1 < len(gs) else (chrono[i + 1]["debut"] if i + 1 < len(chrono) else total)
            fin_groupe = min(fin_groupe, suivant - 0.02, total)
            for j, m in enumerate(g):
                d = c["debut"] + m["debut"]
                f = c["debut"] + g[j + 1]["debut"] if j + 1 < len(g) else fin_groupe
                if f <= d:
                    continue
                morceaux = []
                for k, w in enumerate(g):
                    mot = echapper(w["mot"])
                    if k < j:
                        morceaux.append(f"{{\\c{OR if w['fort'] else BLANC}}}{mot}")
                    elif k == j:
                        gros = "\\fs%d" % (int((taille_hook if st == "Hook" else taille_sub) * 1.12))
                        morceaux.append(f"{{\\c{OR}{gros if w['fort'] else ''}\\b1}}{mot}{{\\r}}")
                    else:
                        morceaux.append(f"{{\\c{GRIS}}}{mot}")
                anim = "{\\fscx94\\fscy94\\t(0,70,\\fscx100\\fscy100)}" if j == 0 else ""
                lignes.append(f"Dialogue: 0,{ass_temps(d)},{ass_temps(f)},{st},,0,0,0,,{anim}" + " ".join(morceaux))
    # motion design : mot fort projeté en grand, au-dessus des sous-titres
    for i, c in enumerate(chrono):
        for m in mots_script(c["mots"], c["affiche"]):
            if not m["fort"]:
                continue
            d = c["debut"] + m["debut"]
            mot = echapper(re.sub(r"[.,;:!?]+$", "", m["mot"]).upper())
            lignes.append(f"Dialogue: 2,{ass_temps(d)},{ass_temps(min(d + 0.95, total))},Choc,,0,0,0,,"
                          f"{{\\pos(540,700)\\fscx170\\fscy170\\alpha&H60&\\blur2\\t(0,140,\\fscx100\\fscy100\\alpha&H00&\\blur0)"
                          f"\\t(650,950,\\fscx112\\fscy112\\alpha&HFF&)}}{mot}")
    # accroche : la première phrase en cartouche blanc, en haut, pendant les premières secondes
    if chrono:
        accroche = titre or re.split(r"(?<=[.!?:])\s", chrono[0]["affiche"].replace("*", ""))[0]
        accroche = couper_lignes(echapper(accroche.rstrip(".:")), 22)
        fin_acc = min(max(chrono[0]["fin"] + 0.6, 2.8), total)
        lignes.append(f"Dialogue: 3,{ass_temps(0)},{ass_temps(fin_acc)},Titre,,0,0,0,,"
                      f"{{\\pos(540,430)\\fscx80\\fscy80\\t(0,160,\\fscx100\\fscy100)\\fad(0,250)}}{accroche}")
    # barre de progression en haut de l'écran
    lignes.append(f"Dialogue: 4,{ass_temps(0)},{ass_temps(total)},Barre,,0,0,0,,"
                  f"{{\\pos(0,0)\\fscx0\\t(0,{int(total * 1000)},\\fscx100)\\p1}}m 0 0 l 1080 0 l 1080 9 l 0 9{{\\p0}}")
    if fin_texte:
        lignes.append(f"Dialogue: 1,{ass_temps(total - 2.4)},{ass_temps(total)},Fin,,0,0,0,,{{\\fad(300,200)}}{echapper(fin_texte)}")
    chemin.write_text(entete + "\n".join(lignes) + "\n", encoding="utf-8")


# ─────────────────────────── principal ───────────────────────────
def main() -> None:
    TRAV.mkdir(exist_ok=True)
    spec = json.loads((EP / "script.json").read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    style = plan.get("style", "intime")
    finale = EP / "voix" / "finale"
    phrases = json.loads((finale / "phrases.json").read_text(encoding="utf-8"))
    pauses = {p["n"]: float(p.get("pause", 0.3)) for p in spec["phrases"]}
    affiches = {p["n"]: p["affiche"] for p in spec["phrases"]}

    # 1. Voix : enchaînement avec les pauses du script
    t = DEBUT
    chrono, morceaux = [], []
    sr = None
    for p in phrases:
        y, sr_ = sf.read(finale / f"s{p['n']:02d}.wav", dtype="float32")
        if y.ndim > 1:
            y = y.mean(axis=1)
        sr = sr or sr_
        chrono.append({"n": p["n"], "debut": t, "fin": t + len(y) / sr, "mots": p["mots"], "affiche": affiches[p["n"]]})
        morceaux.append(y)
        pause = pauses.get(p["n"], 0.3)
        morceaux.append(np.zeros(int(pause * sr), dtype="float32"))
        t += len(y) / sr + pause
    total = t - pauses.get(phrases[-1]["n"], 0) + QUEUE
    voix = np.concatenate([np.zeros(int(DEBUT * sr), dtype="float32")] + morceaux)
    voix = np.concatenate([voix, np.zeros(max(0, int(total * sr) - len(voix)), dtype="float32")])
    sf.write(TRAV / "voix_brute.wav", voix, sr)
    (TRAV / "chrono.json").write_text(json.dumps(
        [{"n": c["n"], "debut": round(c["debut"], 3), "fin": round(c["fin"], 3), "texte": affiches[c["n"]].replace("*", "")}
         for c in chrono], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(chrono)} phrases, {total:.1f} s", flush=True)

    # 2. Plans : un par phrase, durée = phrase + pause
    plans = plan["plans"]
    segments, deja = [], {str(x) for x in plan.get("exclure", [])}
    debuts_plans = []
    for i, c in enumerate(chrono):
        fin_plan = chrono[i + 1]["debut"] if i + 1 < len(chrono) else total
        debut_plan = 0.0 if i == 0 else c["debut"]
        debuts_plans.append(debut_plan)
        duree = fin_plan - debut_plan + (TRANS if i + 1 < len(chrono) else 0)
        p = plans[min(i, len(plans) - 1)]
        if "fichier" in p:
            src, debut = Path(p["fichier"]), float(p.get("debut", 0))
            seg = TRAV / f"seg{i:02d}.mp4"
            segment(src, debut, duree, i, style, seg, float(p.get("x", 0.5)))
        else:
            seg = TRAV / f"seg{i:02d}.mp4"
            graine = spec.get("graine_musique", 7) * 31 + i
            if duree > COUPE_MAX:
                # phrase longue : plusieurs plans en coupe franche, l'image ne reste jamais figée plus de ~2,5 s
                n = min(3, int(-(-duree // 2.6)))
                parts, reste = [], duree
                for j in range(n):
                    dj = round(reste / (n - j), 3)
                    reste -= dj
                    part = TRAV / f"seg{i:02d}{'abc'[j]}.mp4"
                    q = p["q"] if j == 0 else p.get(f"q{j + 1}", p.get("q2", p["q"]))
                    plan_lumineux(q, deja, graine + 7 * j, dj, i + j, style, part, float(p.get("debut", 0.4)))
                    parts.append(part)
                entrees_p = [x for part in parts for x in ("-i", part)]
                ff(*entrees_p, "-filter_complex", "".join(f"[{j}:v]" for j in range(n)) + f"concat=n={n}:v=1:a=0[v]",
                   "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-r", FPS, seg)
            else:
                plan_lumineux(p["q"], deja, graine, duree, i, style, seg, float(p.get("debut", 0.4)))
        segments.append(seg)
    # transitions modernes entre les plans (xfade), chacune commence au début de la phrase suivante
    entrees, graphe, prec = [], [], "[0:v]"
    for s in segments:
        entrees += ["-i", s]
    for k in range(1, len(segments)):
        effet = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        sortie_k = f"[x{k}]" if k + 1 < len(segments) else "[vout]"
        graphe.append(f"{prec}[{k}:v]xfade=transition={effet}:duration={TRANS}:offset={debuts_plans[k]:.3f}{sortie_k}")
        prec = sortie_k
    if len(segments) == 1:
        graphe = ["[0:v]null[vout]"]
    ff(*entrees, "-filter_complex", ";".join(graphe), "-map", "[vout]", "-c:v", "libx264", "-preset", "veryfast",
       "-crf", "17", "-r", FPS, TRAV / "plans.mp4")
    transitions_t = debuts_plans[1:]

    # 3. Musique composée, mixage
    graine = spec.get("graine_musique", 7)
    compositeur = "musique_coach.py" if style == "coach" else "musique.py"
    subprocess.run(["python3", ICI / compositeur, TRAV / "musique.mid", str(graine), f"{total + 5:.2f}"], check=True)
    sf2 = next(p for p in ["/usr/share/sounds/sf3/MuseScore_General_Full.sf3", "/usr/share/sounds/sf2/FluidR3_GM.sf2"]
               if Path(p).exists())
    subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.7", "-r", "48000", "-o", "synth.reverb.active=1",
                    "-o", "synth.reverb.room-size=0.82", "-o", "synth.reverb.level=0.7", "-o", "synth.chorus.active=0",
                    "-F", TRAV / "musique.wav", sf2, TRAV / "musique.mid"], check=True, capture_output=True)

    def lufs(f: Path) -> float:
        m = subprocess.run(["ffmpeg", "-hide_banner", "-i", f, "-af", "ebur128", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
        return float(re.findall(r"I:\s+(-?[\d.]+) LUFS", m)[-1])
    gv, gm = 10 ** ((-17 - lufs(TRAV / "voix_brute.wav")) / 20), 10 ** (((-30 if style == "coach" else -27) - lufs(TRAV / "musique.wav")) / 20)
    if style == "coach":
        voix_fx = (f"aresample=48000,volume={gv:.3f},highpass=f=90,equalizer=f=150:t=q:w=1:g=3,equalizer=f=2800:t=q:w=1.2:g=3,"
                   "acompressor=threshold=-22dB:ratio=5:attack=4:release=120:makeup=5,alimiter=limit=0.95")
    else:
        voix_fx = (f"aresample=48000,volume={gv:.3f},highpass=f=75,equalizer=f=180:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.2:g=1.5,"
                   "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=180:makeup=2")
    fabriquer_bruitages(transitions_t, total, style, TRAV / "sfx.wav")
    ff("-i", TRAV / "voix_brute.wav", "-i", TRAV / "musique.wav", "-i", TRAV / "sfx.wav", "-filter_complex",
       f"[0:a]{voix_fx},asplit=2[v1][v2];"
       f"[1:a]highpass=f=55,equalizer=f=2500:t=q:w=1.5:g=-4,volume={gm:.3f},afade=t=in:d=0.8,"
       f"afade=t=out:st={total - 1.6:.2f}:d=1.6,atrim=0:{total:.3f}[m];"
       "[m][v2]sidechaincompress=threshold=0.05:ratio=2:attack=40:release=700:makeup=1[md];"
       f"[v1][md][2:a]amix=inputs=3:duration=first:normalize=0,apad=whole_dur={total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[a]",
       "-map", "[a]", "-ar", "48000", "-c:a", "pcm_s16le", TRAV / "mix.wav")

    # 4. Sous-titres et rendu final
    ecrire_ass(chrono, spec.get("fin", ""), total, style, TRAV / "st.ass", plan.get("titre", ""))
    ass = str(TRAV / "st.ass").replace("\\", "/").replace(":", "\\:")
    ff("-i", TRAV / "plans.mp4", "-i", TRAV / "mix.wav",
       "-vf", f"subtitles='{ass}':fontsdir='{FONTS}',fade=t=out:st={total - 0.5:.2f}:d=0.5,format=yuv420p",
       "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-profile:v", "high",
       "-tune", "film", "-r", FPS,
       "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", SORTIE)
    ff("-ss", "1.0", "-i", SORTIE, "-frames:v", "1", "-q:v", "2", SORTIE.with_name(SORTIE.stem + "_couverture.jpg"))
    print("MONTÉ", SORTIE, f"{total:.1f} s", flush=True)


if __name__ == "__main__":
    main()
