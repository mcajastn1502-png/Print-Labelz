import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, re
from harness import *
from lab import render
from PIL import Image, ImageDraw

def lab_render(zpl, w_mm, h_mm, dpi=203):
    dpmm = {203: 8, 300: 12, 600: 24}[dpi]
    blocks = re.findall(r"\^XA.*?\^XZ", zpl, re.I | re.S)
    z = blocks[-1] if blocks else zpl
    return render(z, round(w_mm / 25.4, 3), round(h_mm / 25.4, 3), dpmm).convert("RGB")

def compare(name, size=None, dpi=203, cols=COLS, out=None, settings=None):
    z = templates()[name]
    p = LL.parse_template(z, name)
    orig = LL.legacy_fill(z, make_resolver(cols))
    r = LL.compose(z, name, make_resolver(cols), *(size or (None, None)), dpi=dpi, labeler=labeler, settings=settings)
    a = lab_render(orig, p.pw / 8 * 25.4 / 25.4, p.ll / 8, 203)  # original at its own dots
    b = lab_render(r.zpl, r.width_mm, r.height_mm, dpi)
    d = ImageDraw.Draw(b)
    dpmm = LL.dots_per_mm(dpi); m = (settings or LL.LayoutSettings()).margin_mm * dpmm
    d.rectangle([m, m, b.width - m, b.height - m], outline=(255, 0, 0))
    if b.height != a.height:
        s = a.height / b.height
        b = b.resize((int(b.width * s), a.height))
    canvas = Image.new("RGB", (a.width + b.width + 30, max(a.height, b.height)), (200, 200, 200))
    canvas.paste(a, (0, 0)); canvas.paste(b, (a.width + 30, 0))
    out = out or re.sub(r"\W+", "_", name)[:40] + f"_{size}_{dpi}.png"
    canvas.save(out)
    print(name, size, dpi, r.mode, r.warnings, r.notes[:6], "->", out)
    return r

if __name__ == "__main__":
    import json
    for args in json.loads(sys.argv[1]):
        compare(*args[:1], tuple(args[1]) if len(args) > 1 and args[1] else None, *(args[2:3]))
