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
CACHE = Path.home() / "cache_pexels"
BANQUE = Path("tiktok/banque/index.json")
FONTS = ICI.parent.parent / "templates" / "fonts"
W, H, FPS = 1080, 1920, 30
DEBUT = 0.12            # la voix démarre tout de suite
QUEUE = 1.3             # après la dernière phrase
OR = "&H3CC8FF&"        # doré (BGR)
BLANC = "&HFFFFFF&"
GRIS = "&H9A9A9A&"


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
    cands = [v for v in index.values() if isinstance(v, dict) and v.get("q") == q and v["id"] not in deja]
    if not cands:
        cands = [v for v in index.values() if isinstance(v, dict) and q.split()[0] in v.get("q", "") and v["id"] not in deja]
    if not cands:
        raise SystemExit(f"aucun plan en banque pour « {q} »")
    cands.sort(key=lambda v: (-v.get("note", 0), abs(v.get("lum", 60) - 55)))
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
    if f.exists() and f.stat().st_size > 100_000:
        return f
    url = clip["fichier"]["lien"]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(f, "wb") as o:
        shutil.copyfileobj(r, o)
    return f


def segment(src: Path, debut: float, duree: float, k: int, style: str, sortie: Path, x: float = 0.5) -> None:
    """Plan recadré plein écran avec zoom lent (alterné avant / arrière), étalonné."""
    dispo = duree_fichier(src)
    if debut + duree > dispo - 0.1:
        debut = max(0.0, dispo - duree - 0.1)
    z0, z1 = (1.02, 1.11) if k % 2 == 0 else (1.12, 1.03)
    pente = (z1 - z0) / max(duree, 0.1)
    zoom = f"({z0}+{pente:.5f}*t)"
    couv = "max(1920/ih\\,1080/iw)"
    grade = ("eq=contrast=1.15:saturation=0.7:brightness=0.0:gamma=0.98,vignette=PI/4.5,noise=alls=4:allf=t+u"
             if style == "intime" else
             "eq=contrast=1.22:saturation=0.85:brightness=-0.02,vignette=PI/4.6,noise=alls=3:allf=t+u")
    vf = (f"trim=start={debut:.3f}:duration={duree + 0.1:.3f},setpts=PTS-STARTPTS,fps={FPS},"
          f"scale=w='ceil(iw*{couv}*{zoom}/2)*2':h='ceil(ih*{couv}*{zoom}/2)*2':eval=frame,"
          f"crop={W}:{H}:x='(iw-{W})*{x:.3f}',{grade},format=yuv420p,trim=duration={duree:.3f}")
    ff("-i", src, "-an", "-vf", vf, "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", sortie)


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
        fin_ponct = re.search(r"[.!?:;,]$", m["mot"]) is not None
        if len(cur) >= 4 or (fin_ponct and len(cur) >= 2):
            res.append(cur)
            cur = []
    if cur:
        if res and len(cur) == 1:
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


def ecrire_ass(chrono: list[dict], fin_texte: str, total: float, style: str, chemin: Path) -> None:
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
Style: Fin,Cormorant Garamond,66,{OR},{OR},&H000000&,&H80000000&,0,1,0,0,100,100,0,0,1,2,1,2,80,80,400,1

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
    segments, deja = [], set()
    for i, c in enumerate(chrono):
        fin_plan = chrono[i + 1]["debut"] if i + 1 < len(chrono) else total
        duree = fin_plan - c["debut"] + (DEBUT if i == 0 else 0)
        p = plans[min(i, len(plans) - 1)]
        if "fichier" in p:
            src, debut = Path(p["fichier"]), float(p.get("debut", 0))
            seg = TRAV / f"seg{i:02d}.mp4"
            segment(src, debut, duree, i, style, seg, float(p.get("x", 0.5)))
        else:
            seg = TRAV / f"seg{i:02d}.mp4"
            for clip in candidats(p["q"], deja, spec.get("graine_musique", 7) * 31 + i):
                try:
                    src = telecharger(clip)
                except Exception as e:
                    print(f"  plan {i + 1}: {clip['id']} injoignable ({e})", flush=True)
                    continue
                segment(src, float(p.get("debut", 0.4)), duree, i, style, seg)
                lum = luminance(seg)
                if lum >= 22:
                    deja.add(clip["id"])
                    print(f"  plan {i + 1}: {clip['id']} « {clip['q']} » ({clip['auteur']}), lum {lum:.0f}", flush=True)
                    break
                print(f"  plan {i + 1}: {clip['id']} trop sombre (lum {lum:.0f}), autre plan", flush=True)
            else:
                raise SystemExit(f"aucun plan assez lumineux pour « {p['q']} »")
        segments.append(seg)
    (TRAV / "liste.txt").write_text("".join(f"file '{s.resolve()}'\n" for s in segments), encoding="utf-8")
    ff("-f", "concat", "-safe", "0", "-i", TRAV / "liste.txt", "-c", "copy", TRAV / "plans.mp4")

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
    ff("-i", TRAV / "voix_brute.wav", "-i", TRAV / "musique.wav", "-filter_complex",
       f"[0:a]{voix_fx},asplit=2[v1][v2];"
       f"[1:a]highpass=f=55,equalizer=f=2500:t=q:w=1.5:g=-4,volume={gm:.3f},afade=t=in:d=0.8,"
       f"afade=t=out:st={total - 1.6:.2f}:d=1.6,atrim=0:{total:.3f}[m];"
       "[m][v2]sidechaincompress=threshold=0.05:ratio=2:attack=40:release=700:makeup=1[md];"
       f"[v1][md]amix=inputs=2:duration=first:normalize=0,apad=whole_dur={total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[a]",
       "-map", "[a]", "-ar", "48000", "-c:a", "pcm_s16le", TRAV / "mix.wav")

    # 4. Sous-titres et rendu final
    ecrire_ass(chrono, spec.get("fin", ""), total, style, TRAV / "st.ass")
    ass = str(TRAV / "st.ass").replace("\\", "/").replace(":", "\\:")
    ff("-i", TRAV / "plans.mp4", "-i", TRAV / "mix.wav",
       "-vf", f"subtitles='{ass}':fontsdir='{FONTS}',fade=t=out:st={total - 0.5:.2f}:d=0.5,format=yuv420p",
       "-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", FPS,
       "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", SORTIE)
    ff("-ss", "1.0", "-i", SORTIE, "-frames:v", "1", "-q:v", "2", SORTIE.with_name(SORTIE.stem + "_couverture.jpg"))
    print("MONTÉ", SORTIE, f"{total:.1f} s", flush=True)


if __name__ == "__main__":
    main()
