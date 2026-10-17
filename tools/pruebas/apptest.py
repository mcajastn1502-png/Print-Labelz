import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]   # carpeta del proyecto
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools' / 'calibracion'))
import os as _os
_SALIDA = ROOT / 'tools' / 'pruebas' / 'salida'   # imágenes generadas (ignorada por git)
_SALIDA.mkdir(exist_ok=True); _os.chdir(_SALIDA)

# Las pruebas de la app escriben sibo_print_config.json: se guarda el del
# usuario y se restaura al terminar (o se borra si no existía).
import atexit as _atexit
_CFG = ROOT / "sibo_print_config.json"
_CFG_BAK = _CFG.read_bytes() if _CFG.exists() else None
def _restaurar_config():
    if _CFG_BAK is None:
        _CFG.unlink(missing_ok=True)
    else:
        _CFG.write_bytes(_CFG_BAK)
_atexit.register(_restaurar_config)
import sys, os, re, json, shutil, tempfile
import openpyxl
from tkinter import messagebox
LOG = []
for name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, name, (lambda n: lambda title, msg, **k: LOG.append((n, title, msg)))(name))
ASK = {"answer": True}
messagebox.askyesno = lambda title, msg, **k: (LOG.append(("ask", title, msg)), ASK["answer"])[1]

# Excel sintético
xls = os.path.join(tempfile.gettempdir(), "sibo_test.xlsx")
wb = openpyxl.Workbook(); ws = wb.active
ws.append(["CÓDIGO", "UBICACIÓN/SERIE", "MAC/DESCRIPCION", "BODEGA", "RESPONSABLE", "FECHA", "VALORES", "CANTIDAD"])
ws.append(["10-01-01-001", "UB-GYE-RACK-A-03-02", "CONECTOR RJ-45 CAT6 BLINDADO PARA EXTERIORES CON PROTECCIÓN UV", "BODEGA CENTRAL GUAYAQUIL", "PI: 0001 PF: 0250", "15/10/2026", 125, 1])
ws.append(["10-01-01-002", "UB-2", "CABLE", "B1", "PI: 2 PF: 3", "16/10/2026", 5, 2])
ws.append(["10-01-01-003", "UB-GYE-RACK-A-03-02-NIVEL-4-POSICION-12-EXTRA", "DESCRIPCIÓN MUY LARGA " * 8, "BODEGA CENTRAL GUAYAQUIL KM 10.5 VÍA A LA COSTA " * 2, "PI: 000123456 PF: 000999999", "15/10/2026", 1, 1])
wb.save(xls)

import app as APP
APP.filedialog.askopenfilename = lambda **k: xls
# Impresora simulada
SENT = []
class FakeWP:
    def __getattr__(self, n): return getattr(APP.win32print, n)
APP.win32print.OpenPrinter = lambda name: "h"
APP.win32print.StartDocPrinter = lambda *a: None
APP.win32print.StartPagePrinter = lambda *a: None
APP.win32print.WritePrinter = lambda h, data: SENT.append(data)
APP.win32print.EndPagePrinter = lambda *a: None
APP.win32print.EndDocPrinter = lambda *a: None
APP.win32print.ClosePrinter = lambda *a: None

a = APP.ZebraPrintApp()
a.update()
a.after(100); a.update()
for _ in range(10): a.update(); a.after(30)
print("config:", a.config_path)
print("templates:", len(a.all_templates), "sizes known:", len(a.template_sizes), "combo:", len(a.combo_prn["values"]))
print("dpi:", a.combo_dpi.get(), "size:", a.combo_size.get(), "| opciones:", a.combo_size["values"])
a.preview_api_enabled.set(False)
a.load_excel(); a.update()
print("status sin fila:", a.lbl_layout_status.cget("text"))

def pick(template):
    a.combo_prn.set(template); a.on_prn_selected(None); a.update()

# 1) Plantilla 102x25 en tamaño automático
pick("FORMATO 102x25 POLIPROPILENO PICKING.prn")
a.tree.selection_set(a.tree.get_children()[0]); a.update()
print("1)", a.lbl_layout_status.cget("text"))

# 2) Cambiar a 110x25 -> filtra plantillas
a.combo_size.set("110 × 25 mm"); a.on_size_selected(); a.update()
print("2) plantillas para 110x25:", list(a.combo_prn["values"]), "| actual:", a.combo_prn.get())
print("   ", a.lbl_layout_status.cget("text"))

# 3) 300 dpi
a.combo_dpi.set("300 dpi"); a.on_dpi_selected(); a.update()
print("3)", a.lbl_layout_status.cget("text"), "| ^PW:", re.findall(r"\^PW\d+", a.last_layout.zpl))

# 4) Fila con datos largos -> advertencia
a.combo_size.set("51 × 25 mm"); a.on_size_selected(); a.update()
pick("51x25-RESINA-ZEBRA.prn")
a.tree.selection_set(a.tree.get_children()[2]); a.update()
print("4)", a.lbl_layout_status.cget("text")[:160])

# 5) Imprimir 3 filas: debe preguntar por la fila larga; responder "no" y luego "sí"
a.combo_printer.set("ZDesigner TEST 203dpi"); a.on_printer_selected(); a.update()
print("5) dpi deducido del driver:", a.combo_dpi.get())
a.tree.selection_set(a.tree.get_children()); a.update()
a.spin_copies.delete(0, "end"); a.spin_copies.insert(0, "1")
ASK["answer"] = False; LOG.clear(); SENT.clear()
a.print_labels(); a.update()
print("   preguntas:", [l[1] for l in LOG], "| enviados:", len(SENT))
ASK["answer"] = True; LOG.clear(); SENT.clear()
a.print_labels(); a.update()
print("   preguntas:", [l[1] for l in LOG], "| enviados:", len(SENT))
summary = [l for l in LOG if l[1] == "Resumen de impresión"]
print("   resumen:", summary[0][2].replace("\n", " | ") if summary else None)
print("   cada envío es una etiqueta completa:", all(d.count(b"^XZ") >= 1 for d in SENT))

# 6) Ajustes de diseño: cambiar margen vía config y comprobar persistencia
a.layout_settings.margin_mm = 1.0; a._save_app_config()
print("6) config guardada:", json.load(open(a.config_path, encoding="utf-8")))

# 7) Detalle
LOG.clear(); a.show_layout_details(); print("7) detalle:\n", LOG[-1][2][:700])
a.destroy()
