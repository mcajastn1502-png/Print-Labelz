import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, re, json
from harness import *
from lab import render, bbox

DATASETS = {
    "normal": COLS,
    "corto": ["A-1", "U1", "CABLE", "B1", "PI:1 PF:2", "01/01/2026", "1", "1"],
    "largo": ["10-01-01-001-ABCDEF-XYZ", "UB-GYE-RACK-A-03-02-NIVEL-4-POSICION-12",
              "CONECTOR RJ-45 CAT6 BLINDADO PARA EXTERIORES CON PROTECCIÓN UV Y CUBIERTA DE GOMA TERMOCONTRAÍBLE COLOR NEGRO",
              "BODEGA CENTRAL GUAYAQUIL KM 10.5 VÍA A LA COSTA", "PI: 000123456 PF: 000999999", "15/10/2026 14:35:00", "12500", "3"],
    "vacio": ["10-01-01-001", "", "", "", "", "", "", ""],
}
T = templates()
sizes = {n: LL.parse_template(z, n).size_mm for n, z in T.items()}
jobs = []
for name in T:
    jobs.append((name, None, 203))
for size in LL.LABEL_SIZES:
    for name in LL.templates_for_size(size, sizes):
        if tuple(sizes[name]) != tuple(size):
            jobs.append((name, size, 203))
mode = sys.argv[1] if len(sys.argv) > 1 else "normal"
dpis = [203, 300] if mode == "normal" else [203]
summary = {"ok": 0, "warn": 0, "ink_out": 0, "errors": 0}
problems = []
for name, size, _ in jobs:
    for dpi in dpis:
        z = T[name]
        try:
            r = LL.compose(z, name, make_resolver(DATASETS[mode]), *(size or (None, None)), dpi=dpi, labeler=labeler)
        except Exception as e:
            summary["errors"] += 1; problems.append((name, size, dpi, "EXCEPTION", repr(e))); continue
        dpmm = {203: 8, 300: 12}[dpi]
        blocks = re.findall(r"\^XA.*?\^XZ", r.zpl, re.I | re.S)
        try:
            img = render(blocks[-1], round(r.width_mm / 25.4, 3), round(r.height_mm / 25.4, 3), dpmm)
        except Exception as e:
            summary["errors"] += 1; problems.append((name, size, dpi, "RENDER", str(e)[:80])); continue
        b = bbox(img)
        m = 2.0 * LL.dots_per_mm(dpi)
        Wd, Hd = round(r.width_mm * LL.dots_per_mm(dpi)), round(r.height_mm * LL.dots_per_mm(dpi))
        out = b and (b[0] < m - 1 or b[1] < m - 1 or b[2] > Wd - m + 1 or b[3] > Hd - m + 1)
        if r.warnings:
            summary["warn"] += 1
        if out:
            summary["ink_out"] += 1
            problems.append((name, size, dpi, "INK_OUT", f"{b} vs {img.size} m={m}"))
        elif not r.warnings:
            summary["ok"] += 1
        for w in r.warnings:
            problems.append((name, size, dpi, "WARN", w))
print(mode, len(jobs) * len(dpis), summary)
for p in problems: print("  ", p)
