# Herramientas de calibración y pruebas

Scripts usados para construir y verificar el ajuste automático de etiquetas
(`label_layout.py`). Se ejecutan con el Python que ya tiene las dependencias de la
app. `requests` y `openpyxl` son obligatorias; `segno` solo para `qrcap.py`.

Varios scripts envían ZPL de prueba a la API pública de **Labelary**
(api.labelary.com), así que necesitan internet. Labelary limita a unas
3 peticiones/segundo; `lab.py` ya espera entre llamadas y reintenta.
Las respuestas se guardan en `calibracion/cache/` para no repetir peticiones.
Usan datos sintéticos, nunca filas reales del Excel.

## calibracion/

Mediciones de cómo dibuja ZPL Labelary (el mismo motor de la vista previa).
Los resultados ya están incorporados como constantes en `label_layout.py`:
solo hace falta volver a correrlos si cambia la fuente o el motor de render.

| Script | Qué mide |
|---|---|
| `lab.py` | Utilidad común: `render(zpl, ancho_in, alto_in, dpmm)` y `bbox(img)`. |
| `e1.py` | Posición de `^FO`/`^FT`, `^FB`, rotaciones N/B/I/R, QR, Code128, `^GB`. |
| `e2.py` | Ancho de cada carácter de la fuente `^A0` → `adv.json`. |
| `e3.py` | Tamaño del QR según dato y corrección de errores; desplazamiento de `^FO`. |
| `e4.py`, `e8.py` | Code128 y su texto de interpretación; anclaje de `^GF` con `^FT`. |
| `e5.py`, `e6.py`, `e9.py` | `^FH` y saltos `\&`; tildes con `^CI0`, `^CI27`, `^CI28`. |
| `e7.py` | Verificación de anchos llamativos (el guion "-" mide ~0,9 em). |
| `e10.py` | Tamaño de Aztec (`^BO`) según longitud → `aztec.json`. |
| `qrcap.py` | Capacidad de QR por versión (requiere `segno`). |

## pruebas/

Ejecutar desde cualquier carpeta; las imágenes se guardan en `pruebas/salida/`.

| Script | Uso |
|---|---|
| `harness.py` | Datos de prueba y resolución de variables (lo importan los demás). |
| `run1.py` | Analiza las plantillas y compone cada una a su tamaño; lista advertencias y la asociación tamaño → plantillas. Sin red. |
| `viz.py` | Imagen comparativa original vs. adaptada con el área útil marcada. Ej.: `python viz.py '[["F64X30 VOID USUARIO-ASIGNACION.prn"], ["102x25-GAVETAS.prn", [110, 25], 300]]'` |
| `batch.py` | Verificación masiva en Labelary: todas las plantillas y tamaños, a 203/300 dpi, comprueba tinta fuera del área útil. `python batch.py normal` (también `corto`, `largo`, `vacio`). |
| `temas.py` | Abre la app con cada tema de `theme.py` y guarda una captura de la ventana (`salida/tema_<clave>.png`). **Abre la ventana.** |
| `inyeccion.py` | Seguridad de los datos: un valor del Excel con `^`/`~` no añade comandos y las tildes vuelven íntegras según `^FH`/`^CI`, en `legacy_fill` y en el modo adaptado (203/300 dpi). Sin red. |
| `overlap.py` | Renderiza cada campo por separado y detecta superposiciones reales. |
| `apptest.py`, `apptest2.py`, `apptest3.py` | Manejan la app real de forma automática (impresora simulada, diálogos sustituidos): tamaños, dpi, impresión con advertencias, vista previa y diálogo de ajustes. **Abren la ventana unos segundos.** Guardan y restauran `sibo_print_config.json`. |

Rendimiento de referencia: ~12 ms por etiqueta (`run1.py` + `cProfile`).
