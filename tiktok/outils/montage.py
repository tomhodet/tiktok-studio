"""Montage d'un épisode TikTok : plans, voix, sous-titres animés, musique. Sortie 1080x1920, 30 i/s.

Usage : python3 montage.py <episode> [voix]      voix : « Karti » (Chatterbox) ou « kyutai:fabieng »

Mise en page : fond noir, image au format 9:8 au centre (façon plan de cinéma), titre de la série
en haut, sous-titres dorés sur le bas de l'image, carton de fin. Tout reste dans la zone que
l'interface de TikTok ne recouvre pas.
"""
import html
import json
import os
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))
REPO = ICI.parent.parent
FONTS = REPO / "templates" / "fonts"
EP = Path(sys.argv[1]).resolve()
# VARIANTE=xxx : autre mise en page du même épisode (script_xxx.json, dossier _travail_xxx, sortie suffixée)
VARIANTE = os.environ.get("VARIANTE", "")
TRAV = EP / ("_travail" + (f"_{VARIANTE}" if VARIANTE else ""))
W, H, FPS = 1080, 1920, 30
IMG_Y, IMG_H = 480, 960            # cadre image : 1080 x 960, centré (y=480 à y=1440)
FONDU = 0.35                        # fondu enchaîné entre deux plans (s)
DEBUT_VOIX = 0.35                   # la voix démarre presque tout de suite : l'accroche compte
FIN_TENUE = 4.0                     # durée après la dernière phrase (carton de fin)
DUREE_MIN = 62.5                    # au moins 1 min 02 (rémunération : plus d'une minute)

# Réglages de plan : point d'entrée (s), cadrage horizontal ou vertical (0 à 1), vitesse
REGLAGES = {}


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)], check=True)


def lire_wav(chemin: Path) -> tuple[np.ndarray, int]:
    import soundfile as sf
    y, sr = sf.read(str(chemin), dtype="float32")
    if y.ndim > 1:
        y = y.mean(axis=1)
    return y, sr


def ecrire_wav(chemin: Path, y: np.ndarray, sr: int) -> None:
    y16 = np.clip(y, -1, 1)
    y16 = (y16 * 32767).astype(np.int16)
    with wave.open(str(chemin), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(y16.tobytes())


# ─────────────────────────── Sous-titres : découpage et horaires ───────────────────────────

NBSP = "\u00a0"


def preparer(texte: str) -> list[str]:
    """Mots affichés, avec espaces insécables devant ? ! : ; » et après « (ils restent collés au mot)."""
    t = texte.replace("'", "’")
    t = re.sub(r" ([?!:;»])", NBSP + r"\1", t)
    t = t.replace("« ", "«" + NBSP)
    return [m for m in t.split(" ") if m]


PETITS = {"je", "tu", "il", "on", "te", "me", "se", "le", "la", "les", "l’", "de", "du", "des", "d’", "un", "une",
          "ne", "n’", "à", "au", "aux", "et", "que", "qu’", "qui", "pour", "sans", "dans", "en", "ce", "ça", "mes",
          "tes", "ton", "ta", "mon", "ma", "sa", "son", "ses", "nos", "vos", "leur", "y", "j’", "c’", "s’",
          "si", "mais", "ou", "par", "sur", "avec", "comme"}
PREPOSITIONS = {"pour", "à", "au", "aux", "de", "du", "des", "dans", "sur", "avec", "sans", "en", "par", "comme"}
LARGEUR = 30   # caractères au plus par sous-titre


def _long(g: list[str]) -> int:
    return len(" ".join(g))


def _couper(g: list[str]) -> list[list[str]]:
    """Coupe un groupe trop long en deux parts équilibrées, jamais après un petit mot ni un guillemet ouvrant."""
    if _long(g) <= LARGEUR or len(g) < 2:
        return [g]
    meilleur, cout_min = 1, None
    for j in range(1, len(g)):
        gauche, droite = g[:j], g[j:]
        cout = abs(_long(gauche) - _long(droite))
        dernier = gauche[-1].lower()
        if dernier in PETITS or dernier.startswith("«") and "»" not in dernier:
            cout += 100
        if droite[0].lower() in PREPOSITIONS:
            cout -= 3          # on coupe volontiers avant une préposition
        if cout_min is None or cout < cout_min:
            meilleur, cout_min = j, cout
    return _couper(g[:meilleur]) + _couper(g[meilleur:])


def jetons(texte: str) -> list[tuple[str, bool]]:
    """Mots affichés et mise en valeur : les mots entre astérisques (*je t'aime*) sortent en doré."""
    res, etat = [], False
    for tok in preparer(texte):
        n = tok.count("*")
        res.append((tok.replace("*", ""), etat or n > 0))
        if n % 2:
            etat = not etat
    return res


def morceaux(texte: str) -> list[list[str]]:
    """Sous-titres courts : une proposition par sous-titre quand elle tient, sinon coupée en parts équilibrées.
    Les propositions d'un ou deux mots (« Un jour, ») se joignent à la suivante si l'ensemble tient."""
    props, cour = [], []
    for m, _ in jetons(texte):
        cour.append(m)
        if m[-1] in ".,;:!?»":
            props.append(cour)
            cour = []
    if cour:
        props.append(cour)
    joints, i = [], 0
    while i < len(props):
        if len(props[i]) <= 2 and i + 1 < len(props) and _long(props[i] + props[i + 1]) <= LARGEUR:
            joints.append(props[i] + props[i + 1])
            i += 2
        else:
            joints.append(props[i])
            i += 1
    return [part for g in joints for part in _couper(g)]


def horaires_mots(affiche: str, mots_whisper: list[dict], duree: float) -> list[tuple[float, float]]:
    """Horaire de chaque mot affiché, interpolé sur la chronologie des mots reconnus
    (par position dans le texte), pour tolérer les petites différences de transcription."""
    mots = [m for m, _ in jetons(affiche)]
    long_aff = sum(len(m) for m in mots) or 1
    if not mots_whisper:
        pas = duree / len(mots)
        return [(i * pas, (i + 1) * pas) for i in range(len(mots))]
    pos_w, t_w = [0.0], [mots_whisper[0]["debut"]]
    long_w = sum(len(w["mot"]) for w in mots_whisper) or 1
    cumul = 0
    for w in mots_whisper:
        cumul += len(w["mot"])
        pos_w.append(cumul / long_w)
        t_w.append(w["fin"])
    res, cumul = [], 0
    for m in mots:
        a = cumul / long_aff
        cumul += len(m)
        b = cumul / long_aff
        res.append((float(np.interp(a, pos_w, t_w)), float(np.interp(b, pos_w, t_w))))
    return res


# ─────────────────────────── Montage ───────────────────────────

def main() -> None:
    global IMG_Y, IMG_H
    TRAV.mkdir(exist_ok=True)
    spec = json.loads((EP / (f"script_{VARIANTE}.json" if VARIANTE else "script.json")).read_text(encoding="utf-8"))
    if spec.get("plein"):          # plein écran : la vidéo occupe tout le 9:16, sans bandeau de titre
        IMG_Y, IMG_H = 0, H
    plans = json.loads((EP / "plans.json").read_text(encoding="utf-8")) if (EP / "plans.json").exists() else {}
    reglages = {**REGLAGES, **spec.get("reglages", {})}
    choix = sys.argv[2] if len(sys.argv) > 2 else ""
    moteur, _, vid = choix.rpartition(":")
    base_voix = EP / ("voix_kyutai" if moteur == "kyutai" else "voix")
    if vid and (base_voix / vid / "bilan.json").exists():
        bilan = {vid: json.loads((base_voix / vid / "bilan.json").read_text())}
    else:
        bilan = json.loads((base_voix / "bilan.json").read_text())
    vid = vid or min(bilan, key=lambda k: bilan[k]["wer_moyen"])
    phrases = json.loads((base_voix / vid / "phrases.json").read_text())
    print("voix retenue :", moteur or "chatterbox", vid, bilan[vid])

    # 1. Voix : phrases et silences, horaires de chaque phrase
    sr_voix = None
    morceaux_audio, chrono = [], []
    t = DEBUT_VOIX
    tempo = spec.get("tempo_voix", 1.0)       # < 1 : voix un peu plus posée, sans changer le timbre
    for ph, info in zip(spec["phrases"], phrases):
        src = base_voix / vid / f"s{ph['n']:02d}.wav"
        if tempo != 1.0:
            dst = TRAV / f"voix_s{ph['n']:02d}.wav"
            ff("-i", src, "-filter:a", f"atempo={tempo}", dst)
            src = dst
            info = {**info, "mots": [{**m, "debut": m["debut"] / tempo, "fin": m["fin"] / tempo} for m in info["mots"]]}
        y, sr = lire_wav(src)
        info = {**info, "duree": len(y) / sr}
        sr_voix = sr_voix or sr
        chrono.append({"n": ph["n"], "debut": t, "fin": t + len(y) / sr, "info": info, "ph": ph})
        morceaux_audio.append((t, y))
        t += len(y) / sr + ph["pause"]
    fin_voix = chrono[-1]["fin"]
    total = max(fin_voix + FIN_TENUE, DUREE_MIN)
    voix = np.zeros(int(total * sr_voix) + 1, dtype=np.float32)
    for debut, y in morceaux_audio:
        i = int(debut * sr_voix)
        voix[i:i + len(y)] += y
    ecrire_wav(TRAV / "voix_brute.wav", voix, sr_voix)
    (TRAV / "chrono.json").write_text(json.dumps(
        [{"n": c["n"], "debut": round(c["debut"], 3), "fin": round(c["fin"], 3), "texte": c["ph"]["voix"]} for c in chrono],
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"durée voix {fin_voix:.1f} s, vidéo {total:.1f} s")

    # Plans : un par phrase, ou plusieurs (« plan » en liste, « coupes » = mots où changer de plan)
    plans_ord = []
    for k, c in enumerate(chrono):
        noms = c["ph"]["plan"] if isinstance(c["ph"]["plan"], list) else [c["ph"]["plan"]]
        debut = 0.0 if k == 0 else c["debut"] - 0.2
        plans_ord.append((noms[0], debut))
        if len(noms) > 1:
            hor = horaires_mots(c["ph"]["affiche"], c["info"]["mots"], c["info"]["duree"])
            jets = [m.lower().strip("«»,.;:!?\u00a0 ") for m, _ in jetons(c["ph"]["affiche"])]
            for nom_b, mot in zip(noms[1:], c["ph"]["coupes"]):
                i = next(j for j, m in enumerate(jets) if m == mot.lower())
                plans_ord.append((nom_b, c["debut"] + hor[i][0] - 0.12))
    coupes = [t for _, t in plans_ord]
    segs = []
    reutiliser = os.environ.get("REUTILISER_IMAGES") == "1" and (TRAV / "images.mp4").exists()
    if spec.get("fond") and not reutiliser:
        # Fond continu (déjà étalonné, grain et zoom compris) : une seule vidéo verticale recadrée dans le cadre 9:8
        f = spec["fond"]
        d_fond = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                       str(REPO / f["video"])], capture_output=True, text=True).stdout)
        # Fond plus court que la vidéo : léger ralenti (quelques %) plutôt qu'une boucle, pour que son fondu
        # au noir tombe à la toute fin et que le visage ne réapparaisse pas sous le carton final.
        etire = max(1.0, total / d_fond)
        ff("-i", REPO / f["video"], "-an", "-vf",
           f"setpts={etire:.5f}*PTS,crop={W}:{IMG_H}:0:(ih-{IMG_H})*{f.get('cadrage', 0.5)},setsar=1,fps={FPS},format=yuv420p",
           "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-t", f"{total:.3f}", TRAV / "images.mp4")
        reutiliser = True
    for k, (nom, _) in enumerate(plans_ord if not reutiliser else []):
        fin = coupes[k + 1] if k + 1 < len(coupes) else total
        d = fin - coupes[k] + (FONDU if k + 1 < len(coupes) else 0)
        r = reglages.get(nom, {})
        info = plans[nom]
        paysage = info["largeur"] >= info["hauteur"]
        entree = r.get("entree", 0.6)
        vitesse = r.get("vitesse", 1.0)
        dispo = min(info["duree"], 14) - entree
        if dispo * (1 / vitesse) < d:
            vitesse = max(0.6, dispo / d)          # plan trop court : léger ralenti
        cad = r.get("cadrage", 0.5)
        if paysage:   # 1920x1080 -> 1215x1080 -> 1080x960
            filtre = f"crop=1215:1080:(iw-1215)*{cad}:0,scale={W}:{IMG_H}"
        else:         # 1080x1920 -> 1080x960
            filtre = f"crop=1080:960:0:(ih-960)*{cad},scale={W}:{IMG_H}"
        grade = ("eq=saturation=0.8:contrast=1.07:brightness=-0.025:gamma=0.97,"
                 "colorbalance=rs=0.05:gs=0.01:bs=-0.06:rm=0.03:bm=-0.04:rh=0.02:bh=-0.03,"
                 "vignette=angle=PI/4.5,noise=alls=6:allf=t+u")
        sortie = TRAV / f"seg{k:02d}.mp4"
        n_img = max(1, round(d * FPS))
        ampl = r.get("zoom", 0.07)
        z = f"1+{ampl}*on/{n_img}" if k % 2 == 0 else f"{1 + ampl}-{ampl}*on/{n_img}"
        mouvement = (f"scale={2 * W}:{2 * IMG_H}:flags=lanczos,zoompan=z='{z}':x='iw/2-(iw/zoom/2)':"
                     f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{IMG_H}:fps={FPS}")
        ff("-ss", f"{entree:.2f}", "-t", f"{d * vitesse + 0.2:.3f}", "-i", EP / "plans" / f"{nom}.mp4",
           "-vf", f"{filtre},setpts={1 / vitesse:.4f}*PTS,fps={FPS},{mouvement},{grade},setsar=1,format=yuv420p",
           "-an", "-c:v", "libx264", "-crf", "14", "-preset", "veryfast", "-t", f"{d:.3f}", sortie)
        segs.append((sortie, d))
    # Fondus enchaînés
    entrees, graphe, precedent = [], [], "[0:v]"
    for s, _ in segs:
        entrees += ["-i", s]
    for k in range(1, len(segs)):
        sortie = f"[x{k}]" if k + 1 < len(segs) else "[vbase]"
        graphe.append(f"{precedent}[{k}:v]xfade=transition=fade:duration={FONDU}:offset={coupes[k]:.3f}{sortie}")
        precedent = sortie
    if not reutiliser:
        ff(*entrees, "-filter_complex", ";".join(graphe), "-map", "[vbase]", "-c:v", "libx264", "-crf", "14",
           "-preset", "veryfast", "-t", f"{total:.3f}", TRAV / "images.mp4")

    # 3. Sous-titres : horaire de chaque mot, groupes courts, mots mis en valeur
    st = []
    for c in chrono:
        hor = horaires_mots(c["ph"]["affiche"], c["info"]["mots"], c["info"]["duree"])
        jets = jetons(c["ph"]["affiche"])
        i = 0
        for g in morceaux(c["ph"]["affiche"]):
            mots = [{"mot": jets[i + j][0], "fort": jets[i + j][1],
                     "debut": round(c["debut"] + hor[i + j][0], 3), "fin": round(c["debut"] + hor[i + j][1], 3)}
                    for j in range(len(g))]
            i += len(g)
            st.append({"debut": mots[0]["debut"] - 0.06, "fin": mots[-1]["fin"], "mots": mots})
    for k in range(len(st)):     # chaque sous-titre reste jusqu'au suivant, dans la limite de 0,6 s de silence
        suivant = st[k + 1]["debut"] if k + 1 < len(st) else st[k]["fin"] + 0.8
        st[k]["fin"] = round(suivant - 0.18, 3) if suivant - st[k]["fin"] < 0.6 else round(st[k]["fin"] + 0.35, 3)
    (TRAV / "sous_titres.json").write_text(json.dumps(st, ensure_ascii=False, indent=2))

    # 4. Musique composée pour la durée exacte, puis mixage avec la voix
    graine = spec.get("graine_musique", 7)
    subprocess.run(["python3", ICI / "musique.py", TRAV / "musique.mid", str(graine), f"{total + 5.0:.2f}"], check=True)
    subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.7", "-r", "48000", "-o", "synth.reverb.active=1",
                    "-o", "synth.reverb.room-size=0.82", "-o", "synth.reverb.damp=0.35", "-o", "synth.reverb.width=90",
                    "-o", "synth.reverb.level=0.75", "-o", "synth.chorus.active=0", "-F", TRAV / "musique.wav",
                    "/usr/share/sounds/sf3/MuseScore_General_Full.sf3", TRAV / "musique.mid"], check=True,
                   capture_output=True)
    mesure = subprocess.run(["ffmpeg", "-hide_banner", "-i", TRAV / "musique.wav", "-af", "ebur128", "-f", "null", "-"],
                            capture_output=True, text=True).stderr
    lufs = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", mesure)[-1])
    mesure_v = subprocess.run(["ffmpeg", "-hide_banner", "-i", TRAV / "voix_brute.wav", "-af", "ebur128", "-f", "null", "-"],
                              capture_output=True, text=True).stderr
    lufs_v = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", mesure_v)[-1])
    # Voix à -18 LUFS, musique 9 dB en dessous (-27 LUFS) avant l'effacement sous la voix :
    # la voix domine nettement, la musique se fait entendre dans les silences.
    gain_voix = 10 ** ((-18 - lufs_v) / 20)
    gain_musique = 10 ** ((-27 - lufs) / 20)
    debut_fin = total - 1.8
    ff("-i", TRAV / "voix_brute.wav", "-i", TRAV / "musique.wav", "-filter_complex",
       # voix : nettoyage léger, chaleur, niveau constant
       f"[0:a]aresample=48000,volume={gain_voix:.3f},highpass=f=75,equalizer=f=180:t=q:w=1:g=2,equalizer=f=3200:t=q:w=1.2:g=1.5,"
       "acompressor=threshold=-20dB:ratio=2.5:attack=8:release=180:makeup=2,asplit=2[v1][v2];"
       # musique : grave allégé, creusée là où parle la voix, baissée sous la voix
       f"[1:a]highpass=f=55,equalizer=f=2500:t=q:w=1.5:g=-4,volume={gain_musique:.3f},"
       f"afade=t=in:d=1.2,afade=t=out:st={debut_fin:.2f}:d=1.8,atrim=0:{total:.3f}[m];"
       "[m][v2]sidechaincompress=threshold=0.05:ratio=2:attack=40:release=700:makeup=1[md];"
       "[v1][md]amix=inputs=2:duration=first:normalize=0,"
       f"apad=whole_dur={total:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[a]",
       "-map", "[a]", "-ar", "48000", "-c:a", "pcm_s16le", TRAV / "mix.wav")

    # 5. Couche de motion design (titre, sous-titres animés, lueurs, pellicule, carton de fin)
    from motion import rendre_couche
    lueurs = [chrono[i - 1]["debut"] - 0.2 for i in spec.get("lueurs", []) if 0 < i <= len(chrono)]
    donnees = {"fps": FPS, "total": round(total, 3), "episode": spec["episode"], "titre": spec.get("serie") or "",
               "sans_titre": not spec.get("serie"), "sans_avance": bool(spec.get("plein")),
               "fin": spec.get("fin", "Envoie-lui cette vidéo."), "fin_voix": round(fin_voix, 3),
               "st": st, "lueurs": lueurs[:3]}
    # Sous-titres : bas de l'image en 9:8 ; en plein écran, au-dessus de la zone couverte par l'interface TikTok
    y_st = spec.get("y_sous_titres", 1130 if spec.get("plein") else IMG_Y + IMG_H - 300 - 10)
    if not (os.environ.get("REUTILISER_COUCHE") == "1" and (TRAV / "couche.mkv").exists()):
        rendre_couche(donnees, TRAV / "couche.mkv", W, H, IMG_Y, IMG_H, y_st)

    # 6. Assemblage final
    entrees = ["-f", "lavfi", "-i", f"color=c=0x0D0D0D:s={W}x{H}:r={FPS}:d={total:.3f}",
               "-i", TRAV / "images.mp4", "-i", TRAV / "couche.mkv", "-i", TRAV / "mix.wav"]
    graphe = [f"[0:v][1:v]overlay=0:{IMG_Y}:shortest=0[b0]",
              "[2:v]format=rgba[c]",
              "[b0][c]overlay=0:0:eof_action=pass[b1]",
              f"[b1]fade=t=out:st={total - 0.7:.3f}:d=0.7,format=yuv420p[v]"]
    etiquette = vid if not moteur else f"{moteur}_{vid}"
    sortie = EP / f"{EP.name}_{etiquette}{'_' + VARIANTE if VARIANTE else ''}.mp4"
    ff(*entrees, "-filter_complex", ";".join(graphe), "-map", "[v]", "-map", "3:a",
       "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-profile:v", "high",
       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", sortie)
    print("ok", sortie, f"{total:.1f} s")


if __name__ == "__main__":
    main()
