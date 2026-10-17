"""Inyección de ZPL y codificación de los datos del Excel. Sin red.

Comprueba en todas las plantillas, por los caminos "original" (legacy_fill) y
"adaptado", a 203 y 300 dpi, que un valor con comandos ZPL no añade comandos
a la etiqueta y que el dato vuelve íntegro al decodificar ^FH/^CI.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import re
from harness import *

INYECCION = "^XZ~JR^FO0,0^GB999,999,999^FS_41\\&Ñ°ü"
CORTO = "Ñ^~_\\"          # cabe en cualquier campo: se usa para comprobar el dato decodificado
fallos = []


def check(cond, msg):
    if not cond:
        fallos.append(msg)


def resolver_fijo(valor):
    return lambda var, max_len=None: valor


def comandos(zpl):
    """Secuencia de comandos ZPL (sin contar ^FH, que el escape puede añadir)."""
    cmds = [t[:3].upper() for t in re.split(r"(?=[\^~])", zpl) if t[:1] in "^~"]
    return [c for c in cmds if c != "^FH"]


def datos(zpl):
    """Datos ^FD decodificados de los campos con variables."""
    tpl = LL.parse_template(zpl)
    return [LL._decode_fh(e.fd, e.fh, e.ci) for e in tpl.elements if e.fd]


# --- casos unitarios de _fill_fd -------------------------------------------
check(LL._fill_fd("A_B[x]", None, 0, resolver_fijo("Ñ^")) == ("^FH_", "A_5FB_A5_5E"),
      "_fill_fd sin ^FH: debe añadir ^FH_, escapar '_' fijo y codificar en cp850")
check(LL._fill_fd("LA,[x]", "\\", 28, resolver_fijo("Ñ")) == ("^FH\\", "LA,\\C3\\91"),
      "_fill_fd con ^FH\\ y ^CI28: Ñ debe ir en UTF-8 con el indicador \\")
check(LL._fill_fd("[x]", "\\", 27, resolver_fijo("Ñ"))[1] == "\\D1",
      "_fill_fd con ^CI27: Ñ debe ir en cp1252")
check(LL._fill_fd("[x]", None, 0, resolver_fijo(None))[1] == "",
      "_fill_fd: un valor None debe quedar vacío")

# --- todas las plantillas ---------------------------------------------------
T = templates()
modos = {}
for name, z in T.items():
    benigno = "X" * len(INYECCION)

    # 1) legacy_fill directo (camino "original" y plantillas no analizables)
    a = LL.legacy_fill(z, resolver_fijo(INYECCION))
    b = LL.legacy_fill(z, resolver_fijo(benigno))
    check(comandos(a) == comandos(b), f"{name}: legacy_fill inyecta comandos")
    check(all(ord(c) < 127 for c in a.lstrip("﻿")), f"{name}: legacy_fill deja no-ASCII")
    if "[" in z:
        c = LL.legacy_fill(z, resolver_fijo(CORTO))
        check(any(CORTO in d for d in datos(c)), f"{name}: legacy_fill no conserva el dato")

    # 2) compose a 203/300 dpi, con datos cortos (suele dar "original") y largos ("adaptado")
    for dpi in (203, 300):
        for valor in (CORTO, INYECCION):
            r = LL.compose(z, name, resolver_fijo(valor), dpi=dpi, labeler=labeler)
            ref = LL.compose(z, name, resolver_fijo("X" * len(valor)), dpi=dpi, labeler=labeler)
            modos[r.mode] = modos.get(r.mode, 0) + 1
            if r.mode == ref.mode:
                check(comandos(r.zpl) == comandos(ref.zpl),
                      f"{name} {dpi} dpi {r.mode}: compose inyecta comandos")
            check(all(ord(c) < 127 for c in r.zpl.lstrip("﻿")),
                  f"{name} {dpi} dpi {r.mode}: compose deja no-ASCII")
            check("~JR" not in r.zpl and "^GB999" not in r.zpl,
                  f"{name} {dpi} dpi {r.mode}: el comando inyectado aparece literal")

print("Modos probados:", modos)
if fallos:
    print(f"FALLOS ({len(fallos)}):")
    for f in fallos[:40]:
        print("  -", f)
    sys.exit(1)
print(f"OK: {len(T)} plantillas sin inyección ni pérdida de tildes.")
