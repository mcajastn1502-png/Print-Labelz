# SIBO PRINT (copia local de trabajo)

Aplicación de escritorio (Python + Tkinter, Windows) que imprime etiquetas Zebra
desde un Excel usando plantillas ZPL (`prn_templates/*.prn`). Se distribuye como
`.exe` portable con PyInstaller (`ZebraTNPrint.spec`, modo un solo archivo).

## Repositorio y despliegue

- Esta carpeta es una **copia local** de `C:\wamp64\www\SiboPrint`. **No hacer push a
  `Lchango/SIBO-PRINT`** (la cuenta `mcajastn1502-png` no tiene permiso; dio 403).
- `origin` = repo propio del usuario `https://github.com/mcajastn1502-png/Print-Labelz`
  (desde 2026-10-17), con `main` y `feature/ajuste-automatico-etiquetas` publicadas.
- Rama de trabajo: `feature/ajuste-automatico-etiquetas`. Commits locales libres;
  push solo cuando el usuario lo pida.
- `sibo_print_config.json` (ajustes por instalación) está en `.gitignore`.
- Compilar el portable en un entorno virtual limpio con solo `pyinstaller pillow
  openpyxl requests pywin32`: con el Python global se cuelan numpy/lxml y el `.exe`
  pasa de ~25 MB a ~42 MB. El zip portable lleva el `.exe` + `prn_templates/`
  (14 .prn + `ETIQUETAS BARP-2.xlsx`); el usuario confirmó ese contenido.
- Dentro del `.exe` solo van `prn_templates/*.prn` (el `.spec` excluye `archivo/` y el
  Excel). `prn_templates/archivo/` guarda duplicados exactos retirados (ver `LEEME.txt`);
  la app no lee subcarpetas. El usuario prefiere NO normalizar todos los nombres.

## Estructura del código

`app.py` (arranque, construcción de la interfaz, carga de Excel/PRN, resolución de
variables y `_run_async`) define `ZebraPrintApp`, que hereda de mixins por área:
`ui_widgets.py` (botones, tarjetas, fondo), `ui_table.py` (tabla y copias por fila),
`ui_preview.py` (vista previa y Labelary), `ui_printing.py` (copias, impresión,
calibración), `ui_layout.py` (config, tamaño, dpi, diálogo de ajustes). Además:
`label_layout.py` (motor de ajuste), `excel_reader.py`, `theme.py` (temas; no escribir
colores a mano en la interfaz), `app_paths.py` (`app_dir`, `resource_path`).

## Ajuste automático de etiquetas (`label_layout.py`)

Decisiones del usuario (no cambiar sin preguntar):
- **Híbrido**: si la plantilla cumple tal cual se imprime original; si no, se recompone.
- **Resolución mixta 203/300 dpi**, configurable por impresora (se deduce del nombre del driver).
- **Tamaños sin plantilla propia** se derivan de la más cercana (100×100←102×102,
  50×25←51×25, 64×30←60×30/64×25, 110×25←102×25).
- **Mínimos "estándar"**: margen 2 mm, texto 1,5 mm, módulo QR 0,375 mm, zona libre
  QR 2 módulos, separación 1 mm, módulo Code128 0,25 mm.
- **Si no cabe: avisar y preguntar** antes de imprimir (no bloquear).
- **Tamaño físico = el del nombre del archivo** aunque `^PW/^LL` digan otra cosa
  (p. ej. plantillas 945×1181 puntos llamadas "100x150").
- **Tamaño automático + cambiable**; logotipos **reescalados proporcionalmente**.
- Prioridad: redistribuir antes de reducir tipografía; nunca abreviar ni eliminar datos;
  conservar jerarquía (un valor no se aleja de su rótulo salvo como último recurso).

Hechos medidos contra Labelary (base de la geometría; no "corregir" a ojo):
- `^FO` texto = tope de la celda; `^FT` = línea base a 0,75·alto. `^FT`+`^FB` ancla la
  línea base de la ÚLTIMA línea posible. Rotaciones B e I tienen geometría propia.
- `^BQ` con `^FO` dibuja 10 puntos más abajo (también a 300 dpi); con `^FT` el tope es
  `y − (módulos+3)·mag`. `^BO` (Aztec) sin desplazamiento.
- Ancho de `^A0` depende solo del parámetro de ancho; el guion "-" mide ~0,9 em.
- Code128 `^BC` modo N = subconjunto B: `(11·n + 35) × módulo`; texto de interpretación
  ~6·módulo por carácter, centrado.
- Con `^FH\` el salto `\&` de `^FB` NO funciona: el motor emite `^FH_`.
- `^GFA,a,b,c`: con Z64 el total de la imagen es `b`, no `a`.
- Tildes/Ñ: codificar según el `^CI` vigente de cada campo (CI0→cp850, CI27→cp1252,
  CI28→UTF-8). Antes la app mandaba UTF-8 con `^CI0` y salía "PROTECCI├ôN".

Verificación: `tools/` tiene los scripts de calibración contra Labelary y las pruebas
(ver `tools/README.md`). Tras cambiar `label_layout.py`, correr al menos
`python tools/pruebas/batch.py corto` y `normal`, `python tools/pruebas/inyeccion.py`
(sin red) y revisar imágenes con `viz.py`.

Seguridad: todo valor del Excel que entra en un `^FD` pasa por `_fill_fd` (escapa con
el indicador `^FH` del campo, añade `^FH_` si falta, y codifica según `^CI`). No
insertar valores con `re.sub` directo: un dato con `^XZ~JR` inyectaría comandos.

Impresión: cada fila se envía UNA vez con `LL.set_print_quantity` (cantidad en el `^PQ`
del último `^XA…^XZ`); todas las plantillas traen un bloque previo de configuración con
`^JUS` que antes se reenviaba por cada copia. Copias por fila 1–999; más de 300 en total
→ aviso con "No" por defecto. Vista previa por HTTPS; su interruptor se guarda en
`sibo_print_config.json` (`preview_web`).

Hilos: red e impresora van por `_run_async(work, on_done)` (hilo + cola revisada con
`after`). `work` NUNCA toca widgets; `on_done` corre en el hilo de Tk. La vista previa
descarta respuestas viejas con `_preview_seq`; `_printing` impide trabajos simultáneos.
Las pruebas que imprimen o piden vista previa deben llamar `esperar(a)` (apptest.py).
Recursos (iconos, fondo) con `resource_path()`: junto al .exe primero, luego `_MEIPASS`.
Los iconos ya no se descargan de icons8 al arrancar.

Pendientes / conocidos:
- Falta validar en impresora física (solo se verificó contra Labelary).
- Ajuste voraz por orden: a veces un texto grande ocupa el espacio y otro no cabe
  (p. ej. 51x25-RESINA a 300 dpi) → advertencia.
- `F32X14-POLIPROPILENO SFP.prn`: el nombre dice 14 mm y `^LL160` = 20 mm; con mínimos
  por defecto la descripción no cabe. El usuario debe decidir alto real y módulo Aztec.
- `102x102 PAPEL PRODUCTO.prn` trae un QR estático en mapa de bits bajo el QR real.
- `60x30 PAPEL EQUIPOS`: series de ~19 caracteres no caben en Code128.
- En la práctica ninguna plantilla sale en modo "original" (el tamaño del nombre no
  coincide con `^PW/^LL` o hay que comprimir por márgenes): todo va por "adaptado".
  **No cambiar**: el usuario lo va a probar primero en pantalla.

## Comunicación

- El usuario escribe en español; responder en español.
