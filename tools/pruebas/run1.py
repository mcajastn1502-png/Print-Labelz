import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
from harness import *
T = templates()
sizes = {}
for name, z in T.items():
    p = LL.parse_template(z, name); sizes[name] = p.size_mm
for name, z in T.items():
    p = LL.parse_template(z, name)
    kinds = {}
    for e in p.elements: kinds[e.kind] = kinds.get(e.kind, 0) + 1
    r = LL.compose(z, name, make_resolver(), dpi=203, labeler=labeler)
    print(f"{name[:46]:46} {p.size_mm} {r.mode:9} warn={len(r.warnings)} {kinds}")
    for w in r.warnings[:3]: print("     !", w)
print()
for size in LL.LABEL_SIZES:
    print(size, LL.templates_for_size(size, sizes))
