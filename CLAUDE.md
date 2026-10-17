# SIBO PRINT (copia local de trabajo)

Aplicación de escritorio (Python + Tkinter, Windows) que imprime etiquetas Zebra
desde un Excel usando plantillas ZPL (`prn_templates/*.prn`). Se distribuye como
`.exe` portable con PyInstaller (`ZebraTNPrint.spec`, modo un solo archivo).

## Repositorio y despliegue

- Esta carpeta es una **copia local** de `C:\wamp64\www\SiboPrint`. Se le quitó el
  remoto `origin` a propósito: **no hacer push a `Lchango/SIBO-PRINT`** (la cuenta
  `mcajastn1502-png` no tiene permiso de escritura; el push dio 403).
- Rama de trabajo: `feature/ajuste-automatico-etiquetas`. Se pueden hacer commits
  locales. Si el usuario quiere publicar, será en un repo propio (`git remote add`).
- `sibo_print_config.json` (ajustes por instalación) está en `.gitignore`.
- Compilar el portable en un entorno virtual limpio con solo `pyinstaller pillow
  openpyxl requests pywin32`: con el Python global se cuelan numpy/lxml y el `.exe`
  pasa de ~25 MB a ~42 MB. El zip portable lleva el `.exe` + `prn_templates/`
  (14 .prn + `ETIQUETAS BARP-2.xlsx`); el usuario confirmó ese contenido.

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
`python tools/pruebas/batch.py corto` y `normal`, y revisar imágenes con `viz.py`.

Pendientes / conocidos:
- Falta validar en impresora física (solo se verificó contra Labelary).
- Ajuste voraz por orden: a veces un texto grande ocupa el espacio y otro no cabe
  (p. ej. 51x25-RESINA a 300 dpi) → advertencia.
- `F32X14-POLIPROPILENO SFP.prn`: el nombre dice 14 mm y `^LL160` = 20 mm; con mínimos
  por defecto la descripción no cabe. El usuario debe decidir alto real y módulo Aztec.
- `102x102 PAPEL PRODUCTO.prn` trae un QR estático en mapa de bits bajo el QR real.
- `60x30 PAPEL EQUIPOS`: series de ~19 caracteres no caben en Code128.

## Comunicación

- El usuario escribe en español; responder en español.
