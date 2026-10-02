"""Image de couverture TikTok d'un épisode (1080x1920, JPEG) : visage du personnage, « Épisode N »,
titre de la série et accroche en doré ; pour un personnage sans série (le fou), l'accroche seule, en grand.

  python3 couverture.py <episode> <sortie.jpg>
Réglages par personnage (tiktok/personnages.json) : couverture_t (instant du fond), couverture_y (décalage
vertical de l'image), couverture_fond (autre vidéo que le fond du montage, au format 9:16).
"""
import html
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FONTS = REPO / "templates" / "fonts"

GABARIT = """<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: C; src: url('__CG__'); font-weight: 300 700; }
@font-face { font-family: CI; src: url('__CGI__'); font-weight: 300 700; }
@font-face { font-family: M; src: url('__MS__'); font-weight: 100 900; }
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1920px; background:#0D0D0D url('__BG__') center __Y__px/1080px auto no-repeat; position:relative; }
.voile { position:absolute; inset:0; background:linear-gradient(180deg, rgba(13,13,13,.1) 0%, rgba(13,13,13,.02) 30%,
         rgba(13,13,13,.6) 56%, rgba(13,13,13,.97) 74%, rgba(13,13,13,1) 100%); }
.bloc { position:absolute; left:0; right:0; top:__TOP__px; text-align:center; padding:0 86px; }
.lab { font-family:M; font-weight:500; font-size:30px; letter-spacing:.45em; color:#C9A96E; text-transform:uppercase; }
.filet { width:140px; height:2px; background:#C9A96E; margin:26px auto 30px; }
.t { font-family:C; font-weight:600; font-size:104px; line-height:1.02; color:#FAFAF8; text-wrap:balance;
     text-shadow:0 4px 30px rgba(0,0,0,.6); }
.t em { font-family:CI; font-style:italic; color:#F2D27C; }
.h { font-family:CI; font-style:italic; font-size:__HS__px; line-height:1.12; color:__HC__; margin-top:44px;
     text-wrap:balance; text-shadow:0 3px 20px rgba(0,0,0,.7); }
</style></head><body><div class="voile"></div><div class="bloc">__CONTENU__</div></body></html>"""


def main() -> None:
    ep, sortie = Path(sys.argv[1]), Path(sys.argv[2])
    spec = json.loads((ep / "script.json").read_text(encoding="utf-8"))
    perso = json.loads((REPO / "tiktok" / "personnages.json").read_text(encoding="utf-8"))[spec["perso"]]
    fond = REPO / perso.get("couverture_fond", perso["fond"]["video"])
    with tempfile.TemporaryDirectory() as tmp:
        bg = Path(tmp) / "bg.png"
        if fond.suffix.lower() in (".png", ".jpg", ".jpeg"):      # image de couverture déjà extraite
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(fond), "-vf", "scale=1080:-2", str(bg)], check=True)
        else:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(perso.get("couverture_t", 3)), "-i", str(fond),
                            "-frames:v", "1", "-vf", "scale=1080:-2", str(bg)], check=True)
        accroche = html.escape(spec.get("accroche") or spec["phrases"][0]["voix"])
        if spec.get("serie"):
            mots = spec["serie"].split(" ")
            # « grand-mère », « grand-père » : jamais coupés ; dernier mot (« jamais ») en doré
            def mot(m: str) -> str:
                return f'<span style="white-space:nowrap">{html.escape(m)}</span>' if "-" in m else html.escape(m)
            titre = " ".join(mot(m) for m in mots[:-1]) + f" <em>{html.escape(mots[-1])}</em>"
            contenu = (f'<div class="lab">Épisode {spec["episode"]}</div><div class="filet"></div>'
                       f'<div class="t">{titre}</div><div class="h">« {accroche} »</div>')
            top, hs, hc = 1020, 58, "#F2D27C"
        else:
            contenu = f'<div class="filet"></div><div class="t" style="font-family:CI;font-style:italic">{accroche}</div>'
            top, hs, hc = 1180, 58, "#F2D27C"
        page = (GABARIT.replace("__CG__", (FONTS / "CormorantGaramond.ttf").as_uri())
                .replace("__CGI__", (FONTS / "CormorantGaramond-Italic.ttf").as_uri())
                .replace("__MS__", (FONTS / "Montserrat.ttf").as_uri())
                .replace("__BG__", bg.as_uri()).replace("__Y__", str(perso.get("couverture_y", -250)))
                .replace("__TOP__", str(top)).replace("__HS__", str(hs)).replace("__HC__", hc)
                .replace("__CONTENU__", contenu))
        (Path(tmp) / "c.html").write_text(page, encoding="utf-8")
        png = Path(tmp) / "c.png"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            pg = nav.new_page(viewport={"width": 1080, "height": 1920})
            pg.goto((Path(tmp) / "c.html").as_uri())
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(300)
            pg.screenshot(path=str(png))
            nav.close()
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(png), "-q:v", "2", str(sortie)], check=True)
    print("ok", sortie)


if __name__ == "__main__":
    main()
