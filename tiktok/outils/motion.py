"""Couche de motion design : rendue image par image dans Chromium (fond transparent), puis
superposée à la vidéo par ffmpeg.

Éléments animés :
- ouverture du cadre façon rideau, titre qui apparaît mot à mot, filet doré qui se trace ;
- sous-titres cinétiques : chaque mot arrive au moment où il est dit (fondu, flou, légère montée),
  les mots forts en doré avec un éclat ;
- lueurs chaudes aux moments clés, poussières et rayures de pellicule, léger scintillement ;
- carton de fin sur voile sombre.
"""
import json
import subprocess
from pathlib import Path

FONTS = Path(__file__).resolve().parents[2] / "templates" / "fonts"

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face { font-family: 'Cormorant'; src: url('__CG__'); font-weight: 300 700; }
@font-face { font-family: 'Cormorant'; src: url('__CGI__'); font-weight: 300 700; font-style: italic; }
@font-face { font-family: 'Montserrat'; src: url('__MS__'); font-weight: 100 900; }
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: __W__px; height: __H__px; background: transparent; overflow: hidden; }
#cadre { position: absolute; left: 0; top: __IY__px; width: __W__px; height: __IH__px; overflow: hidden; }
.volet { position: absolute; left: 0; width: 100%; height: 50%; background: #0D0D0D; }
#v1 { top: 0; } #v2 { bottom: 0; }
#voile { position: absolute; inset: 0; background: #0D0D0D; opacity: 0; }
#scint { position: absolute; inset: 0; background: #fff; opacity: 0; }
.lueur { position: absolute; width: 1100px; height: 1100px; border-radius: 50%; opacity: 0;
         background: radial-gradient(circle, rgba(255,196,120,.85) 0%, rgba(255,140,60,.38) 38%, rgba(255,120,40,0) 68%); }
#poussiere { position: absolute; inset: 0; }
#avance { position: absolute; left: 0; top: __AY__px; height: 2px; width: __W__px; background: #C9A96E;
          transform-origin: left; transform: scaleX(0); opacity: .85; }
#titre { position: absolute; left: 0; top: 0; width: __W__px; height: __IY__px; display: flex; flex-direction: column;
         align-items: center; justify-content: flex-end; padding-bottom: 34px; text-align: center; }
#lab { font-family: Montserrat; font-weight: 500; font-size: 24px; color: #C9A96E; text-transform: uppercase; }
#filet { width: 120px; height: 1px; background: #C9A96E; margin: 16px 0 18px; transform-origin: center; }
#ttl { font-family: Cormorant; font-weight: 500; font-size: 76px; line-height: 1.0; color: #FAFAF8; padding: 0 100px; }
#ttl span { display: inline-block; white-space: pre; }
#st { position: absolute; left: 0; width: __W__px; top: __SY__px; height: 300px; display: flex; align-items: center;
      justify-content: center; text-align: center; padding: 0 110px; }
#st .bloc { font-family: Cormorant; font-style: italic; font-weight: 700; font-size: 82px; line-height: 1.06;
            text-wrap: balance; }
#st .m { display: inline-block; white-space: pre; color: #FBF6EE;
         -webkit-text-stroke: 7px rgba(8,8,8,.9); paint-order: stroke fill; text-shadow: 0 4px 18px rgba(0,0,0,.7); }
#st .m.fort { color: #F2D27C; }
#fin { position: absolute; left: 0; top: __IY__px; width: __W__px; height: __IH__px; display: flex; flex-direction: column;
       align-items: center; justify-content: center; text-align: center; }
#fin .ligne { width: 160px; height: 1px; background: #C9A96E; margin-bottom: 34px; transform: scaleX(0); }
#fin .t { font-family: Cormorant; font-style: italic; font-weight: 500; font-size: 78px; line-height: 1.05; color: #FAFAF8;
         padding: 0 110px; text-wrap: balance; }
#fin .t span { display: inline-block; white-space: pre; opacity: 0; }
</style></head><body>
<div id="cadre">
  <div id="scint"></div>
  <canvas id="poussiere" width="__W__" height="__IH__"></canvas>
  <div class="lueur" id="l0"></div><div class="lueur" id="l1"></div><div class="lueur" id="l2"></div>
  <div id="voile"></div>
  <div class="volet" id="v1"></div><div class="volet" id="v2"></div>
</div>
<div id="avance"></div>
<div id="titre"><div id="lab"></div><div id="filet"></div><div id="ttl"></div></div>
<div id="st"><div class="bloc"></div></div>
<div id="fin"><div class="ligne"></div><div class="t"></div></div>
<script>
const D = __DATA__;
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const easeOut = p => 1 - Math.pow(1 - p, 3);
const easeInOut = p => p < .5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
const prog = (t, a, d) => clamp((t - a) / d, 0, 1);

// Titre (absent en plein écran sans titre)
if (D.sans_titre) document.getElementById('titre').style.display = 'none';
if (D.sans_avance) document.getElementById('avance').style.display = 'none';
document.getElementById('lab').textContent = 'Épisode ' + D.episode;
const ttl = document.getElementById('ttl');
// Titre sur deux lignes équilibrées (jamais un mot seul sur la seconde)
const mt = D.titre ? D.titre.split(' ') : [];
let coupe = 1, ecart = 1e9;
for (let j = 1; j < mt.length; j++) {
  const e = Math.abs(mt.slice(0, j).join(' ').length - mt.slice(j).join(' ').length);
  if (e < ecart) { ecart = e; coupe = j; }
}
const motsTitre = mt.map((m, i) => {
  if (i === coupe) ttl.appendChild(document.createElement('br'));
  const s = document.createElement('span'); s.textContent = m + (i < mt.length - 1 && i !== coupe - 1 ? ' ' : '');
  ttl.appendChild(s); return s;
});
// Fin
const finT = document.querySelector('#fin .t');
const motsFin = D.fin.split(' ').map((m, i, a) => { const s = document.createElement('span'); s.textContent = m + (i < a.length - 1 ? ' ' : ''); finT.appendChild(s); return s; });
// Sous-titres : un bloc de spans par morceau, créé à la demande
const bloc = document.querySelector('#st .bloc');
let courant = -1, spans = [];
function montrer(k) {
  if (k === courant) return;
  courant = k; bloc.innerHTML = ''; spans = [];
  if (k < 0) return;
  D.st[k].mots.forEach((w, i, a) => {
    const s = document.createElement('span');
    s.className = 'm' + (w.fort ? ' fort' : '');
    s.textContent = w.mot + (i < a.length - 1 ? ' ' : '');
    bloc.appendChild(s); spans.push(s);
  });
}
// Poussières : générateur pseudo-aléatoire déterministe
function rng(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
const cv = document.getElementById('poussiere'), cx = cv.getContext('2d');

window.render = function (t) {
  const f = Math.round(t * D.fps);
  // Ouverture du cadre
  const o = easeInOut(prog(t, 0, 0.8));
  document.getElementById('v1').style.transform = `translateY(${-o * 100}%)`;
  document.getElementById('v2').style.transform = `translateY(${o * 100}%)`;
  // Titre
  const pl = easeOut(prog(t, 0.05, 0.9));
  const lab = document.getElementById('lab');
  lab.style.opacity = pl; lab.style.letterSpacing = (0.9 - 0.48 * pl) + 'em';
  document.getElementById('filet').style.transform = `scaleX(${easeInOut(prog(t, 0.3, 0.8))})`;
  motsTitre.forEach((s, i) => {
    const p = easeOut(prog(t, 0.2 + 0.07 * i, 0.55));
    s.style.opacity = p; s.style.transform = `translateY(${(1 - p) * 22}px)`; s.style.filter = `blur(${(1 - p) * 10}px)`;
  });
  // Sous-titres
  let k = -1;
  for (let i = 0; i < D.st.length; i++) { if (t >= D.st[i].debut - 0.05 && t < D.st[i].fin + 0.18) { k = i; } }
  montrer(k);
  if (k >= 0) {
    const c = D.st[k];
    const sortie = prog(t, c.fin, 0.18);
    bloc.style.opacity = 1 - sortie; bloc.style.transform = `translateY(${-sortie * 12}px)`;
    c.mots.forEach((w, i) => {
      const p = easeOut(prog(t, w.debut - 0.04, 0.22));
      const s = spans[i];
      s.style.opacity = p;
      const sc = w.fort ? 1.14 - 0.14 * p : 1;
      s.style.transform = `translateY(${(1 - p) * 22}px) scale(${sc})`;
      s.style.filter = p < 1 ? `blur(${(1 - p) * 8}px)` : 'none';
      if (w.fort) {
        const eclat = Math.max(0, 1 - Math.abs(t - w.debut - 0.25) / 0.6);
        s.style.textShadow = `0 4px 18px rgba(0,0,0,.7), 0 0 ${18 + 26 * eclat}px rgba(242,210,124,${0.25 + 0.5 * eclat})`;
      }
    });
  }
  // Lueurs chaudes
  D.lueurs.forEach((a, i) => {
    const el = document.getElementById('l' + i); if (!el) return;
    const p = prog(t, a - 0.6, 1.5);
    el.style.opacity = Math.sin(Math.PI * p) * 0.55;
    el.style.left = (-700 + p * 1300) + 'px'; el.style.top = (-200 + p * 180) + 'px';
  });
  // Fil doré d'avancement sous l'image
  document.getElementById('avance').style.transform = `scaleX(${clamp(t / D.total, 0, 1)})`;
  document.getElementById('avance').style.opacity = 0.85 * easeOut(prog(t, 0.6, 0.6));
  // Voile et carton de fin
  const pv = easeInOut(prog(t, D.fin_voix + 0.15, 0.8));
  document.getElementById('voile').style.opacity = 0.62 * pv;
  document.querySelector('#fin .ligne').style.transform = `scaleX(${easeInOut(prog(t, D.fin_voix + 0.35, 0.9))})`;
  motsFin.forEach((s, i) => {
    const p = easeOut(prog(t, D.fin_voix + 0.5 + 0.12 * i, 0.6));
    s.style.opacity = p; s.style.transform = `translateY(${(1 - p) * 18}px)`; s.style.filter = `blur(${(1 - p) * 10}px)`;
  });
  // Pellicule : scintillement, poussières, rayures
  const r = rng(f * 7919 + 17);
  document.getElementById('scint').style.opacity = (r() - 0.5) * 0.03 + 0.012;
  cx.clearRect(0, 0, cv.width, cv.height);
  const n = 4 + Math.floor(r() * 7);
  for (let i = 0; i < n; i++) {
    const x = r() * cv.width, y = r() * cv.height, rad = 0.6 + r() * 2.2, blanc = r() < 0.6;
    cx.fillStyle = blanc ? `rgba(255,248,235,${0.18 + r() * 0.3})` : `rgba(0,0,0,${0.2 + r() * 0.3})`;
    cx.beginPath();
    if (r() < 0.3) { cx.ellipse(x, y, rad * 3, rad * 0.6, r() * Math.PI, 0, 2 * Math.PI); } else { cx.arc(x, y, rad, 0, 2 * Math.PI); }
    cx.fill();
  }
  if (r() < 0.07) {
    const x = r() * cv.width, y0 = r() * cv.height * 0.5, h = cv.height * (0.3 + r() * 0.6);
    cx.fillStyle = `rgba(255,250,240,${0.08 + r() * 0.12})`; cx.fillRect(x, y0, 1.2, h);
  }
};
</script></body></html>"""


def rendre_couche(donnees: dict, sortie: Path, largeur: int, hauteur: int, img_y: int, img_h: int, st_y: int) -> None:
    """Rend la couche animée en vidéo sans perte avec transparence (FFV1, RGBA)."""
    from playwright.sync_api import sync_playwright
    html = (PAGE.replace("__CG__", (FONTS / "CormorantGaramond.ttf").as_uri())
            .replace("__CGI__", (FONTS / "CormorantGaramond-Italic.ttf").as_uri())
            .replace("__MS__", (FONTS / "Montserrat.ttf").as_uri())
            .replace("__W__", str(largeur)).replace("__H__", str(hauteur))
            .replace("__IY__", str(img_y)).replace("__IH__", str(img_h)).replace("__SY__", str(st_y))
            .replace("__AY__", str(img_y + img_h))
            .replace("__DATA__", json.dumps(donnees, ensure_ascii=False)))
    page_html = sortie.with_suffix(".html")
    page_html.write_text(html, encoding="utf-8")
    fps, total = donnees["fps"], donnees["total"]
    n = int(round(total * fps))
    ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "png",
                           "-i", "-", "-c:v", "ffv1", "-pix_fmt", "bgra", str(sortie)], stdin=subprocess.PIPE)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        page = nav.new_page(viewport={"width": largeur, "height": hauteur})
        page.goto(page_html.as_uri())
        page.evaluate("document.fonts.ready")
        for i in range(n):
            page.evaluate("t => window.render(t)", i / fps)
            ff.stdin.write(page.screenshot(omit_background=True, type="png"))
        nav.close()
    ff.stdin.close()
    ff.wait()
    page_html.unlink()
