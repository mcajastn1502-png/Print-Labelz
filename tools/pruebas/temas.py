"""Captura de la ventana con cada tema (salida/tema_<clave>.png). Abre la app."""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import json
exec(open(pathlib.Path(__file__).with_name("apptest.py"), encoding="utf-8").read().split("a = APP.ZebraPrintApp()")[0])
from PIL import ImageGrab
import theme as THEME

for key in THEME.THEMES:
    _CFG.write_text(json.dumps({"theme": key}), encoding="utf-8")
    a = APP.ZebraPrintApp()
    a.geometry("1280x760+20+20")
    for _ in range(10): a.update(); a.after(30)
    a.load_excel(); a.update()
    a.combo_prn.set("FORMATO 102x25 POLIPROPILENO PICKING.prn"); a.on_prn_selected(None)
    a.tree.selection_set(a.tree.get_children()[1]); esperar(a)
    a.lift(); a.attributes("-topmost", True)
    for _ in range(20): a.update(); a.after(30)
    x, y = a.winfo_rootx(), a.winfo_rooty()
    img = ImageGrab.grab((x, y, x + a.winfo_width(), y + a.winfo_height()), all_screens=True)
    img.save(f"tema_{key}.png")
    print(key, "->", _SALIDA / f"tema_{key}.png", img.size, "| tema activo:", a.theme.name)
    a.destroy()
