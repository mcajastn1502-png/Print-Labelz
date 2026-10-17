import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)
import sys, os
exec(open(pathlib.Path(__file__).with_name("apptest.py"), encoding="utf-8").read().split("a = APP.ZebraPrintApp()")[0])
import tkinter as tk
cfg = str(ROOT / "sibo_print_config.json")
try:
    a = APP.ZebraPrintApp()
    for _ in range(10): a.update(); a.after(30)
    a.preview_api_enabled.set(False)
    def fill_and_save(values, invalid=None):
        dlg = [w for w in a.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        entries = [w for w in dlg.winfo_children()[0].winfo_children() if isinstance(w, tk.Entry)]
        for e, v in zip(entries, values):
            e.delete(0, "end"); e.insert(0, v)
        dlg.event_generate("<Return>")
    # 1) valor inválido -> error y el diálogo sigue abierto; luego Escape
    a.after(400, lambda: (fill_and_save(["abc"]), a.after(300, lambda: [w for w in a.winfo_children() if isinstance(w, tk.Toplevel)][-1].event_generate("<Escape>"))))
    a.open_design_settings()
    print("1) errores mostrados:", [l[2] for l in LOG if l[0] == "showerror"])
    # 2) valores válidos: margen 3 mm, tamaño personalizado 80 x 40
    a.after(400, lambda: fill_and_save(["3", "1", "1.5", "0.375", "2", "0.25", "80", "40"]))
    a.open_design_settings()
    print("2) margen:", a.layout_settings.margin_mm, "| personalizado:", a._custom_size(), "| opciones:", a.combo_size["values"][-1])
    # 3) seleccionar personalizado
    a.combo_size.set(a.combo_size["values"][-1]); a.on_size_selected(); a.update()
    print("3) plantillas para 80x40:", a.combo_prn["values"][:4], "...", "| estado:", a.lbl_layout_status.cget("text")[:60])
    # 4) tema: elegir "Grafito" en el diálogo -> se guarda y avisa que se aplica al reabrir
    from tkinter import ttk
    def pick_theme(name):
        dlg = [w for w in a.winfo_children() if isinstance(w, tk.Toplevel)][-1]
        combo = [w for w in dlg.winfo_children()[0].winfo_children() if isinstance(w, ttk.Combobox)][0]
        combo.set(name); dlg.event_generate("<Return>")
    LOG.clear()
    a.after(400, lambda: pick_theme("Grafito"))
    a.open_design_settings()
    print("4) tema guardado:", a.app_config.get("theme"), "| aviso:", [l[2] for l in LOG if l[1] == "Tema de la interfaz"])
    a.destroy()
    b = APP.ZebraPrintApp(); b.update()
    print("   al reabrir:", b.theme.name, b.bg_color)
    b.destroy()
finally:
    if os.path.exists(cfg):
        print("config:", open(cfg, encoding="utf-8").read().replace("\n", " ")[:200]); os.remove(cfg)
