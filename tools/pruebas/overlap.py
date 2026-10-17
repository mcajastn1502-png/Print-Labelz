import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, re
from harness import *
from lab import render, bbox
from batch import DATASETS
T = templates()
mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
modes = {"original": 0, "adaptado": 0}
bad = []
for name, z in T.items():
    r = LL.compose(z, name, make_resolver(DATASETS[mode]), dpi=203, labeler=labeler)
    modes[r.mode] = modes.get(r.mode, 0) + 1
    if r.mode != "adaptado":
        continue
    body = re.findall(r"\^XA.*?\^XZ", r.zpl, re.S)[-1]
    hdr = body.split("^F")[0]
    fields = re.findall(r"(?:\^BY[\d.,]+)?(?:\^CI\d+)?\^F[OT][^\n]*?\^FS", body)
    boxes = []
    for f in fields:
        b = bbox(render(hdr + f + "^XZ", round(r.width_mm / 25.4, 3), round(r.height_mm / 25.4, 3), 8))
        if b:
            kind = "box" if "^GB" in f else "graphic" if "^GF" in f else "qr" if "^BQ" in f else "bc" if "^BC" in f else "text"
            boxes.append((kind, b, re.sub(r"(\^GFA,[0-9,]*)[^\^]*", r"\1", f)[:70]))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (ka, a, fa), (kb, b, fb) = boxes[i], boxes[j]
            if {ka, kb} & {"box", "graphic"} and "text" in (ka, kb):
                continue  # texto dentro de recuadro / sobre fondo (permitido si ya era así)
            if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                bad.append((name, ka, a, fa, kb, b, fb, r.warnings))
print(mode, modes, "solapes:", len(bad))
for x in bad: print("  ", x)
