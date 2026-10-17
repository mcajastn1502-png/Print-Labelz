import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, os
exec(open(pathlib.Path(__file__).with_name("apptest.py"), encoding="utf-8").read().split("a = APP.ZebraPrintApp()")[0])
try:
    a = APP.ZebraPrintApp()
    for _ in range(10): a.update(); a.after(30)
    a.load_excel(); a.update()
    for tpl, size, dpi in [("FORMATO 102x25 POLIPROPILENO PICKING.prn", "110 × 25 mm", "203 dpi"),
                           ("102x102 PAPEL PRODUCTO.prn", "100 × 100 mm", "300 dpi"),
                           ("100x150 POLIPROPILENO ARTICULOS.prn", "100 × 150 mm", "203 dpi")]:
        a.combo_size.set(size); a.on_size_selected(); a.update()
        a.combo_dpi.set(dpi); a.on_dpi_selected(); a.update()
        a.combo_prn.set(tpl); a.on_prn_selected(None); a.update()
        a.tree.selection_set(a.tree.get_children()[0]); a.update()
        img = a._current_preview_img
        print(tpl[:35], size, dpi, "->", img.size if img else a.preview_canvas.cget("text"), "|", a.lbl_layout_status.cget("text")[:70])
        if img: img.save(f"app_{size[:3]}_{dpi[:3]}.png")
    a.destroy()
finally:
    cfg = str(ROOT / "sibo_print_config.json")
    if os.path.exists(cfg): os.remove(cfg); print("config de prueba eliminada")
