import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, os, re, glob, textwrap
import label_layout as LL

COLS = ["10-01-01-001", "UB-GYE-RACK-A-03-02", "CONECTOR RJ-45 CAT6 BLINDADO PARA EXTERIORES CON PROTECCIÓN UV",
        "BODEGA CENTRAL GUAYAQUIL", "PI: 0001 PF: 0250", "15/10/2026", "125", "1"]
HEAD = ["CÓDIGO", "UBICACIÓN/SERIE", "MAC/DESCRIPCION", "BODEGA", "RESPONSABLE", "FECHA", "VALORES", "CANTIDAD"]

def make_resolver(cols=COLS):
    def resolver(var, max_len=None):
        if var.lower() == "vlscantidadauto":
            return cols[7]
        m = re.match(r"(?i)^vlscampo(\d+)([a-z])?$", var.strip())
        if not m:
            if var.lower() == "vlscampo": return cols[0]
            return ""
        idx = int(m.group(1)) - 1
        val = cols[idx] if 0 <= idx < len(cols) else ""
        if m.group(2) and max_len:
            chunks = textwrap.wrap(val, width=max_len, break_long_words=True, break_on_hyphens=False)
            p = ord(m.group(2).upper()) - 65
            return chunks[p] if p < len(chunks) else ""
        return val
    return resolver

def labeler(var):
    m = re.match(r"(?i)vlscampo(\d+)", var)
    return f"{HEAD[int(m.group(1))-1]} ({var})" if m and int(m.group(1)) <= len(HEAD) else var

def templates():
    out = {}
    for f in sorted(glob.glob(str(ROOT / "prn_templates" / "*.prn"))):
        out[os.path.basename(f)] = open(f, encoding="utf-8", errors="ignore").read()
    return out
