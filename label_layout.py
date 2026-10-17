"""
Motor de ajuste automático de etiquetas ZPL.

Toma una plantilla .prn, los valores de una fila y un tamaño destino (mm + dpi),
y produce un ZPL que:
  - respeta un área útil (etiqueta menos márgenes de seguridad),
  - redistribuye el texto (ancho, líneas) antes de reducir la tipografía,
  - conserva proporciones de logotipos y códigos QR (con su zona libre),
  - nunca abrevia ni elimina datos: si algo no cabe con los mínimos
    configurados, lo informa como advertencia.

Si la plantilla ya cumple todo en su tamaño nativo, se usa tal cual
(modo "original"); si no, se regenera la composición (modo "adaptado").

Las constantes de geometría (posición de ^FO/^FT, anchos de la fuente ^A0,
desplazamiento de ^BQ, ancho de Code128) se midieron contra Labelary, el
mismo motor que usa la vista previa.
"""

import copy
import math
import re
import textwrap
from dataclasses import dataclass, field, asdict

# Submódulos del motor. Se reexportan para que `import label_layout as LL` y
# LL.parse_template, LL._fill_fd, LL.text_width… sigan funcionando igual.
from zpl_metrics import (  # noqa: F401  (reexportado: LL.<nombre>)
    _A0_ADVANCE,
    _A0_DEFAULT_ADVANCE,
    _ACCENT_RATIO,
    _AZTEC_SIZES,
    _CAP_RATIO,
    _OVERSHOOT_RATIO,
    _QR_ALNUM,
    _QR_DATA_BITS,
    _QR_FO_OFFSET,
    _QR_FT_EXTRA_MODULES,
    _TEXT_SAFETY,
    _barcode_text_height,
    _char_advance,
    _gf_decode_ascii,
    _graphic_ink_box,
    _has_upper_accent,
    _rle_count,
    _split_qr_data,
    _text_em,
    _wrap_cached,
    aztec_modules,
    code128_modules,
    gf_decode,
    gf_encode_ascii,
    gf_resize,
    qr_modules,
    text_width,
    wrap_text,
)
from zpl_geometry import (  # noqa: F401  (reexportado: LL.<nombre>)
    Rect,
    _UnionRect,
    _from_frame,
    _to_frame,
)
from zpl_template import (  # noqa: F401  (reexportado: LL.<nombre>)
    Element,
    ParsedTemplate,
    _FIELD_CMDS,
    _LEGACY_FD_CMDS,
    _LEGACY_FIELD_RESET,
    _PLACEHOLDER_RE,
    _SEGMENT_RE,
    _SIZE_IN_NAME_RE,
    _ci_codec,
    _classify,
    _decode_fh,
    _encode_fd,
    _fill_fd,
    _int,
    _parse_fb,
    _parse_font,
    legacy_fill,
    parse_template,
    template_size_mm,
)

__all__ = [  # API reexportada (evita avisos de import sin uso)
    '_A0_ADVANCE',
    '_A0_DEFAULT_ADVANCE',
    '_ACCENT_RATIO',
    '_AZTEC_SIZES',
    '_CAP_RATIO',
    '_OVERSHOOT_RATIO',
    '_QR_ALNUM',
    '_QR_DATA_BITS',
    '_QR_FO_OFFSET',
    '_QR_FT_EXTRA_MODULES',
    '_TEXT_SAFETY',
    '_barcode_text_height',
    '_char_advance',
    '_gf_decode_ascii',
    '_graphic_ink_box',
    '_has_upper_accent',
    '_rle_count',
    '_split_qr_data',
    '_text_em',
    '_wrap_cached',
    'aztec_modules',
    'code128_modules',
    'gf_decode',
    'gf_encode_ascii',
    'gf_resize',
    'qr_modules',
    'text_width',
    'wrap_text',
    'Rect',
    '_UnionRect',
    '_from_frame',
    '_to_frame',
    'Element',
    'ParsedTemplate',
    '_FIELD_CMDS',
    '_LEGACY_FD_CMDS',
    '_LEGACY_FIELD_RESET',
    '_PLACEHOLDER_RE',
    '_SEGMENT_RE',
    '_SIZE_IN_NAME_RE',
    '_ci_codec',
    '_classify',
    '_decode_fh',
    '_encode_fd',
    '_fill_fd',
    '_int',
    '_parse_fb',
    '_parse_font',
    'legacy_fill',
    'parse_template',
    'template_size_mm',
]

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# Tamaños soportados (ancho × alto en mm).
LABEL_SIZES = [
    (102, 102), (102, 25), (51, 25), (100, 100),
    (100, 150), (50, 25), (64, 30), (110, 25),
]

# Puntos por mm reales de los cabezales Zebra.
_DPMM_BY_DPI = {152: 6, 203: 8, 300: 12, 600: 24}
DPI_OPTIONS = (203, 300, 600)


def dots_per_mm(dpi):
    return _DPMM_BY_DPI.get(int(dpi), dpi / 25.4)


_HOW_LABELS = {
    "widen": "ancho ampliado al espacio libre",
    "deepen": "repartido en más líneas",
    "both": "ancho ampliado y repartido en más líneas",
}


@dataclass
class LayoutSettings:
    margin_mm: float = 2.0            # margen de seguridad en cada borde
    gap_mm: float = 1.0               # separación mínima entre elementos
    min_text_mm: float = 1.5          # altura mínima de texto
    min_qr_module_mm: float = 0.375   # tamaño mínimo de módulo QR
    qr_quiet_modules: int = 2         # zona libre alrededor del QR (módulos)
    min_barcode_module_mm: float = 0.25

    @classmethod
    def from_dict(cls, data):
        base = cls()
        if not isinstance(data, dict):
            return base
        for key, default in asdict(base).items():
            if key in data:
                try:
                    setattr(base, key, type(default)(data[key]))
                except (TypeError, ValueError):
                    pass
        return base

    def to_dict(self):
        return asdict(self)


def orientation_of(width_mm, height_mm):
    ratio = width_mm / float(height_mm)
    if ratio > 1.25:
        return "horizontal"
    if ratio < 0.8:
        return "vertical"
    return "cuadrada"


# =============================================================================
# COMPOSICIÓN
# =============================================================================

@dataclass
class LayoutResult:
    zpl: str
    mode: str                     # original | adaptado | sin_analisis
    warnings: list
    width_mm: float
    height_mm: float
    dpi: int
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.warnings


@dataclass
class _Item:
    """Elemento ya ubicado en coordenadas destino (puntos)."""
    el: Element
    rect: Rect                    # caja ocupada en página
    kind: str
    label: str = ""
    # texto
    text: str = ""
    lines: list = None
    font_h: float = 0
    font_w: float = 0
    spacing: float = 0
    n_lines: int = 1
    along: float = 0
    align: str = "L"
    orient: str = "N"
    elastic: bool = False         # sin ^FB en la plantilla: ancho libre
    pad_up: float = 0             # tilde de mayúsculas por encima de la celda
    # rígidos
    qr_module: int = 0
    qr_size: int = 0
    qr_data: str = ""
    quiet: float = 0
    bc_module: int = 0
    bc_height: int = 0
    bc_text: int = 0
    gf_size: tuple = None
    gb_dims: tuple = None
    fixed: bool = False           # sin cambios respecto al diseño
    changed: bool = False

    def footprint(self):
        """Caja que no debe invadir ningún otro elemento."""
        if self.kind == "qr":
            return self.rect.inflate(self.quiet)
        if self.kind == "barcode" and self.bc_text:
            # Barras + texto de interpretación (monoespaciado, centrado debajo).
            bars = Rect(self.rect.x0, self.rect.y0, self.rect.x1, self.rect.y0 + self.bc_height)
            tw = min(self.rect.w, 6 * self.bc_module * max(len(self.qr_data), 1))
            cx = (self.rect.x0 + self.rect.x1) / 2
            label = Rect(cx - tw / 2, bars.y1, cx + tw / 2, self.rect.y1)
            return bars.union(label) if tw >= self.rect.w else _UnionRect(bars, label)
        if self.kind == "text":
            fr = _to_frame(self.rect, self.orient, 1e6, 1e6)
            lines = self.lines
            if lines is None and self.text.strip():
                lines = wrap_text(self.text, max(fr.w, 1), self.font_w)
            if lines:
                # Solo lo que ocupan las líneas reales, según la alineación.
                used = min(fr.w, max(text_width(l, self.font_w) for l in lines))
                n = len(lines)
                bh = (n - 1) * (self.font_h + self.spacing) + self.font_h
                if self.align == "C":
                    u = fr.x0 + (fr.w - used) / 2
                elif self.align == "R":
                    u = fr.x1 - used
                else:
                    u = fr.x0
                fr = Rect(u, fr.y0, u + used, fr.y0 + min(fr.h, bh) if fr.h else bh)
            fr = Rect(fr.x0, fr.y0 - self.pad_up, fr.x1, fr.y1)
            return _from_frame(fr, self.orient, 1e6, 1e6)
        return self.rect


class _Composer:
    def __init__(self, tpl, resolver, width_mm, height_mm, dpi, settings, labeler=None):
        self.tpl = tpl
        self.resolver = resolver
        self.labeler = labeler or (lambda var: var)
        self.width_mm = float(width_mm)
        self.height_mm = float(height_mm)
        self.dpi = int(dpi)
        self.s = settings
        self.dpmm = dots_per_mm(dpi)
        self.W = int(round(self.width_mm * self.dpmm))
        self.H = int(round(self.height_mm * self.dpmm))
        m = self.s.margin_mm * self.dpmm
        self.safe = Rect(m, m, self.W - m, self.H - m)
        self.gap = self.s.gap_mm * self.dpmm
        self.min_text = max(1, int(math.ceil(self.s.min_text_mm * self.dpmm)))
        self.min_qr = max(1, int(math.ceil(self.s.min_qr_module_mm * self.dpmm - 1e-6)))
        self.min_bc = max(1, int(math.ceil(self.s.min_barcode_module_mm * self.dpmm - 1e-6)))
        self.warnings = []
        self.notes = []
        self.orientation = orientation_of(self.width_mm, self.height_mm)

    # ------------------------------------------------------------- utilidades
    def _fill(self, fd, indicator, ci=None):
        def replace(match):
            return self.resolver(match.group(1), None)
        decoded = _decode_fh(fd, indicator, self.tpl.ci if ci is None else ci)
        return _PLACEHOLDER_RE.sub(replace, decoded)

    def _fill_escaped(self, el):
        """(^FH, datos ^FD) de un código QR/Aztec/de barras con los valores escapados."""
        return _fill_fd(el.fd, el.fh, el.ci, lambda var, max_len: self.resolver(var, None))

    def _label_for(self, el):
        names = [m.group(1) for m in _PLACEHOLDER_RE.finditer(el.fd)]
        if names:
            seg = _SEGMENT_RE.match(names[0])
            var = f"vlsCampo{seg.group(1)}" if seg else names[0]
            return self.labeler(var)
        txt = _decode_fh(el.fd, el.fh, el.ci).strip()
        return f"texto «{txt[:20]}»" if txt else "texto"

    # --------------------------------------------------------- caja de diseño
    def _design_text_rect(self, el, text, n_lines, pitch):
        h = el.font_h
        L = el.fb[0] if el.fb else text_width(text, el.font_w)
        bh = (n_lines - 1) * pitch + h
        x, y, o = el.x, el.y, el.orient
        if el.origin == "FO":
            if o in ("N", "I"):
                return Rect(x, y, x + L, y + bh)
            return Rect(x, y, x + bh, y + L)
        # ^FT
        if o == "N":
            top = y - _CAP_RATIO * h - (n_lines - 1) * pitch
            return Rect(x, top, x + L, top + bh)
        if o == "I":
            top = y - (1 - _CAP_RATIO) * h
            return Rect(x - L, top, x, top + bh)
        if o == "B":
            left = x - _CAP_RATIO * h - (n_lines - 1) * pitch
            return Rect(left, y - L, left + bh, y)
        left = x - (1 - _CAP_RATIO) * h
        return Rect(left, y, left + bh, y + L)

    def _design_rect(self, el):
        """Caja ocupada en el diseño (puntos de la plantilla) con los datos reales."""
        if el.kind == "qr":
            ecc, data = _split_qr_data(self._fill(el.fd, el.fh, el.ci))
            n = qr_modules(data, ecc) or 21
            size = n * el.bq_mag
            top = el.y + _QR_FO_OFFSET if el.origin == "FO" else el.y - (n + _QR_FT_EXTRA_MODULES) * el.bq_mag
            return Rect(el.x, top, el.x + size, top + size)
        if el.kind == "aztec":
            size = aztec_modules(self._fill(el.fd, el.fh, el.ci)) * el.bq_mag
            top = el.y if el.origin == "FO" else el.y - size
            return Rect(el.x, top, el.x + size, top + size)
        if el.kind == "barcode":
            data = self._fill(el.fd, el.fh, el.ci)
            module, ratio, by_h = el.by
            height = _int(el.bc[1], 0) or by_h
            width = code128_modules(data) * module
            text_h = _barcode_text_height(module) if (el.bc[2] or "Y").strip().upper() != "N" else 0
            top = el.y if el.origin == "FO" else el.y - height
            return Rect(el.x, top, el.x + width, top + height + text_h)
        if el.kind == "graphic":
            total, bpr, _ = el.gf
            w, h = bpr * 8, (total // bpr if bpr else 0)
            top = el.y if el.origin == "FO" else el.y - h
            full = Rect(el.x, top, el.x + w, top + h)
            # La impresora recorta lo que sale de la etiqueta: solo cuenta lo
            # visible, y de eso solo la parte con tinta (el blanco no ocupa).
            vis = Rect(max(full.x0, 0), max(full.y0, 0),
                       min(full.x1, self.tpl.pw), min(full.y1, self.tpl.ll))
            if vis.w <= 0 or vis.h <= 0:
                vis = full
            ink = _graphic_ink_box(el)
            if ink:
                inked = Rect(max(vis.x0, full.x0 + ink[0]), max(vis.y0, full.y0 + ink[1]),
                             min(vis.x1, full.x0 + ink[2]), min(vis.y1, full.y0 + ink[3]))
                if inked.w > 0 and inked.h > 0:
                    vis = inked
            el.gf_crop = (int(vis.x0 - full.x0), int(vis.y0 - full.y0),
                          int(vis.x1 - full.x0), int(vis.y1 - full.y0))
            return vis
        if el.kind == "box":
            w, h, t = el.gb[0], el.gb[1], el.gb[2]
            w, h = max(w, t), max(h, t)
            top = el.y if el.origin == "FO" else el.y - h
            return Rect(el.x, top, el.x + w, top + h)
        if el.kind == "text":
            n = el.fb[1] if el.fb else 1
            pitch = el.font_h + (el.fb[2] if el.fb else 0)
            return self._design_text_rect(el, self._static_text(el), n, pitch)
        return Rect(el.x, el.y, el.x + 1, el.y + 1)

    def _static_text(self, el):
        """Texto fijo del campo (sin variables): la caja de diseño no depende
        de los datos de la fila. Mínimo, una celda cuadrada."""
        static = _PLACEHOLDER_RE.sub("", _decode_fh(el.fd, el.fh, el.ci))
        return static if text_width(static, el.font_w) >= el.font_h else "M" * max(1, int(el.font_h / max(el.font_w, 1) / 0.756 + 1))

    # ------------------------------------------------- segmentos vlsCampoNX
    def _merge_segments(self, elements):
        groups = {}
        for el in elements:
            if el.kind != "text":
                continue
            ph = list(_PLACEHOLDER_RE.finditer(el.fd))
            if len(ph) != 1 or ph[0].group(0) != el.fd.strip():
                continue
            seg = _SEGMENT_RE.match(ph[0].group(1))
            if seg:
                groups.setdefault(seg.group(1), []).append((seg.group(2).upper(), el))
        merged = {}
        for base, members in groups.items():
            if len(members) < 2:
                continue
            members.sort(key=lambda m: m[0])
            merged[base] = [el for _, el in members]
        return merged

    # ------------------------------------------------------------- principal
    def compose(self):
        tpl = self.tpl
        els = tpl.elements
        segs = self._merge_segments(els)
        seg_member = {}
        for base, members in segs.items():
            for i, el in enumerate(members):
                seg_member[id(el)] = (base, i, members)

        # 1) Cajas de diseño
        design = {}
        for el in els:
            if id(el) in seg_member and seg_member[id(el)][1] > 0:
                continue
            if id(el) in seg_member:
                base, _, members = seg_member[id(el)]
                rect = None
                for m in members:
                    n = m.fb[1] if m.fb else 1
                    r = self._design_text_rect(m, self._static_text(m), n, m.font_h)
                    rect = r if rect is None else rect.union(r)
                design[id(el)] = rect
            else:
                design[id(el)] = self._design_rect(el)

        # 2) Mapeo diseño -> destino
        sx = self.W / float(tpl.pw)
        sy = self.H / float(tpl.ll)
        content = None
        for el in els:
            if id(el) in design and el.kind != "other":
                content = design[id(el)] if content is None else content.union(design[id(el)])
        if content is None:
            content = Rect(0, 0, tpl.pw, tpl.ll)

        def axis_map(c0, c1, scale, total, s0, s1):
            m0, m1 = c0 * scale, c1 * scale
            length = m1 - m0
            if m0 >= s0 - 0.5 and m1 <= s1 + 0.5:
                return 1.0, 0.0
            k = min(1.0, (s1 - s0) / length) if length > 0 else 1.0
            start = min(max(m0, s0), s1 - length * k)
            return k, start - m0 * k

        kx, ox = axis_map(content.x0, content.x1, sx, self.W, self.safe.x0, self.safe.x1)
        ky, oy = axis_map(content.y0, content.y1, sy, self.H, self.safe.y0, self.safe.y1)
        fx, fy = sx * kx, sy * ky
        rigid = min(fx, fy)
        self.map = (fx, ox, fy, oy)

        def mx(x):
            return x * fx + ox

        def my(y):
            return y * fy + oy

        # Solo es "la misma etiqueta" si el tamaño en puntos coincide y no hubo
        # que comprimir el contenido para respetar los márgenes.
        identity = (abs(self.W - tpl.pw) <= 1 and abs(self.H - tpl.ll) <= 1
                    and kx == 1.0 and ky == 1.0 and abs(ox) < 1 and abs(oy) < 1)
        if not identity:
            self.notes.append(
                f"Escalado {fx:.2f}×{fy:.2f} (diseño {tpl.pw}×{tpl.ll} pt → {self.W}×{self.H} pt).")

        def place_rigid(drect, w, h, anchor=None):
            """Ubica un elemento rígido de w×h dentro de su caja mapeada,
            anclado al lado de la etiqueta más cercano en el diseño (o al
            ancla indicada: 'top'/'bottom')."""
            x0, x1, y0, y1 = mx(drect.x0), mx(drect.x1), my(drect.y0), my(drect.y1)
            cx = (drect.x0 + drect.x1) / 2 / tpl.pw
            cy = (drect.y0 + drect.y1) / 2 / tpl.ll
            nx = x0 if cx < 0.4 else (x1 - w if cx > 0.6 else (x0 + x1 - w) / 2)
            ny = y0 if cy < 0.4 else (y1 - h if cy > 0.6 else (y0 + y1 - h) / 2)
            if anchor == "top":
                nx, ny = x0, y0
            elif anchor == "bottom":
                nx, ny = x0, y1 - h
            return Rect(round(nx), round(ny), round(nx) + w, round(ny) + h)

        # 3) Elementos destino
        items = []
        for el in els:
            if id(el) not in design:
                continue
            d = design[id(el)]
            if el.kind == "qr":
                ecc, data = _split_qr_data(self._fill(el.fd, el.fh, el.ci))
                n = qr_modules(data, ecc)
                if n is None:
                    self.warnings.append(f"El dato del QR es demasiado largo ({len(data)} caracteres).")
                    n = 117
                module = max(self.min_qr, int(round(el.bq_mag * rigid)))
                if module > 10:
                    module = 10
                size = n * module
                # ^FO crece hacia abajo y ^FT hacia arriba, como en la impresora.
                anchor = "top" if el.origin == "FO" else "bottom"
                it = _Item(el=el, rect=place_rigid(d, size, size, anchor), kind="qr",
                           label="código QR", qr_module=module, qr_size=n, qr_data=data,
                           quiet=self.s.qr_quiet_modules * module)
                it.place = (lambda w, h, d=d, a=anchor: place_rigid(d, w, h, a))
                it.fixed = identity and module == el.bq_mag
                items.append(it)
            elif el.kind == "aztec":
                data = self._fill(el.fd, el.fh, el.ci)
                n = aztec_modules(data)
                module = min(10, max(self.min_qr, int(round(el.bq_mag * rigid))))
                size = n * module
                anchor = "top" if el.origin == "FO" else "bottom"
                it = _Item(el=el, rect=place_rigid(d, size, size, anchor), kind="qr",
                           label="código Aztec", qr_module=module, qr_size=n, qr_data=data,
                           quiet=1 * module)
                it.quiet_modules = 1
                it.place = (lambda w, h, d=d, a=anchor: place_rigid(d, w, h, a))
                it.fixed = identity and module == el.bq_mag
                items.append(it)
            elif el.kind == "barcode":
                data = self._fill(el.fd, el.fh, el.ci)
                module = max(self.min_bc, int(round(el.by[0] * rigid)))
                height = max(1, int(round((_int(el.bc[1], 0) or el.by[2]) * rigid)))
                text_h = _barcode_text_height(module) if (el.bc[2] or "Y").strip().upper() != "N" else 0
                width = code128_modules(data) * module
                it = _Item(el=el, rect=place_rigid(d, width, height + text_h), kind="barcode",
                           label=f"código de barras «{data}»", bc_module=module,
                           bc_height=height, bc_text=text_h, qr_data=data)
                it.fixed = identity and module == el.by[0]
                items.append(it)
            elif el.kind == "graphic":
                w0, h0 = int(d.w), int(d.h)
                w, h = max(1, int(round(w0 * rigid))), max(1, int(round(h0 * rigid)))
                it = _Item(el=el, rect=place_rigid(d, w, h), kind="graphic",
                           label="logotipo/gráfico", gf_size=(w, h))
                it.fixed = identity
                items.append(it)
            elif el.kind == "box":
                w, h, t = el.gb[0], el.gb[1], el.gb[2]
                nt = max(1, int(round(t * rigid)))
                x0, x1, y0, y1 = mx(d.x0), mx(d.x1), my(d.y0), my(d.y1)
                if h <= t:   # línea horizontal
                    if d.x0 <= tpl.pw * 0.03 and d.x1 >= tpl.pw * 0.97:
                        x0, x1 = self.safe.x0, self.safe.x1
                    rect = Rect(round(x0), round(y0), round(x1), round(y0) + nt)
                elif w <= t:  # línea vertical
                    if d.y0 <= tpl.ll * 0.03 and d.y1 >= tpl.ll * 0.97:
                        y0, y1 = self.safe.y0, self.safe.y1
                    rect = Rect(round(x0), round(y0), round(x0) + nt, round(y1))
                else:
                    rect = Rect(round(x0), round(y0), round(x1), round(y1))
                it = _Item(el=el, rect=rect, kind="box", label="línea/recuadro",
                           gb_dims=(int(rect.w), int(rect.h), nt))
                it.fixed = identity
                items.append(it)
            elif el.kind == "text":
                items.append(self._make_text_item(el, d, seg_member.get(id(el)), rigid, mx, my))
            else:
                items.append(_Item(el=el, rect=Rect(mx(d.x0), my(d.y0), mx(d.x0) + 1, my(d.y0) + 1),
                                   kind="other", fixed=identity))

        # Relaciones del diseño: elementos que ya se solapaban (texto dentro de un
        # recuadro) quedan exentos; los que estaban a menos de la separación
        # mínima conservan esa cercanía, pero no pueden solaparse.
        exempt, tight = set(), set()
        for i, a in enumerate(items):
            for j, b in enumerate(items):
                if j <= i or "qr" in (a.kind, b.kind) or "other" in (a.kind, b.kind):
                    continue
                da, db = design[id(a.el)], design[id(b.el)]
                if da.intersects(db) and "text" in (a.kind, b.kind) and \
                        {a.kind, b.kind} & {"box", "graphic"}:
                    # Solo se hereda si el texto está completamente dentro de un
                    # marco o de un gráfico de fondo (nunca sobre una línea).
                    text_rect, frame_rect, frame = (da, db, b) if a.kind == "text" else (db, da, a)
                    is_frame = frame.kind == "graphic" or (
                        frame.el.gb and min(frame.el.gb[0], frame.el.gb[1]) > frame.el.gb[2])
                    if is_frame and text_rect.inside(frame_rect, tol=2):
                        exempt.update({(i, j), (j, i)})
                elif da.intersects(db) and a.kind != "text" and b.kind != "text":
                    exempt.update({(i, j), (j, i)})
                else:
                    # Tolerancia: redondeos y el exceso de las letras redondas.
                    font = max(a.el.font_h if a.kind == "text" else 0,
                               b.el.font_h if b.kind == "text" else 0)
                    if da.distance(db) < self.gap / max(rigid, 1e-6) + 2 + 0.05 * font:
                        tight.update({(i, j), (j, i)})
        self.exempt, self.tight = exempt, tight

        # 4) Rígidos: dentro del área útil y sin choques entre ellos
        self._settle_rigid(items)

        # 5) Texto: redistribuir antes de reducir
        order = sorted(range(len(items)), key=lambda i: (items[i].rect.y0, items[i].rect.x0))
        for i in order:
            if items[i].kind == "text":
                self._fit_text(items, i, identity)
        # Segunda pasada: lo que no cupo se reintenta con el resto ya ubicado.
        notes_before = len(self.notes)
        for i in order:
            if items[i].kind == "text" and items[i].fit_warning:
                self._fit_text(items, i, identity)
        for i in order:
            if items[i].kind == "text" and items[i].fit_warning:
                self.warnings.append(items[i].fit_warning)

        # 6) Comprobación final
        self._final_check(items)

        original_ok = identity and not self.warnings and all(
            it.fixed for it in items if it.kind != "text") and all(
            not it.changed for it in items if it.kind == "text")
        if original_ok and self.dpi_matches():
            zpl = legacy_fill(self.source_zpl, self.resolver)
            return LayoutResult(zpl, "original", [], self.width_mm, self.height_mm, self.dpi, self.notes)
        zpl = self._emit(items)
        return LayoutResult(zpl, "adaptado", self.warnings, self.width_mm, self.height_mm,
                            self.dpi, self.notes)

    def dpi_matches(self):
        dx, dy = self.tpl.design_dpmm
        return abs(dx - self.dpmm) / self.dpmm < 0.02 and abs(dy - self.dpmm) / self.dpmm < 0.02

    # ----------------------------------------------------------------- texto
    def _make_text_item(self, el, drect, seg, rigid, mx, my):
        tpl = self.tpl
        if seg:
            base, _, members = seg
            text = self.resolver(_PLACEHOLDER_RE.search(members[0].fd).group(1), None)
            n_lines = len(members)
            if n_lines > 1:
                first = self._design_text_rect(members[0], "", 1, members[0].font_h)
                last = self._design_text_rect(members[-1], "", 1, members[-1].font_h)
                f0 = _to_frame(first, el.orient, tpl.pw, tpl.ll)
                f1 = _to_frame(last, el.orient, tpl.pw, tpl.ll)
                pitch = max(el.font_h, abs(f1.y0 - f0.y0) / (n_lines - 1))
            else:
                pitch = el.font_h
            spacing = pitch - el.font_h
            align = members[0].fb[3] if members[0].fb else "L"
            elastic = not members[0].fb
            # Comprobación del comportamiento histórico (cortes de NN caracteres)
            max_len = _int(_PLACEHOLDER_RE.search(members[0].fd).group(2), 0)
            legacy_chunks = textwrap.wrap(text, width=max_len, break_long_words=True,
                                          break_on_hyphens=False) if max_len else [text]
            legacy_overflow = len(legacy_chunks) > n_lines
        else:
            text = self._fill(el.fd, el.fh, el.ci)
            n_lines = el.fb[1] if el.fb else 1
            spacing = el.fb[2] if el.fb else 0
            align = el.fb[3] if el.fb else "L"
            elastic = not el.fb
            legacy_chunks = None
            legacy_overflow = False

        # Mapear la caja de diseño
        page = Rect(mx(drect.x0), my(drect.y0), mx(drect.x1), my(drect.y1))
        fr = _to_frame(page, el.orient, self.W, self.H)
        h = el.font_h * rigid
        w = el.font_w * rigid
        sp = spacing * rigid
        it = _Item(el=el, rect=page, kind="text", label=self._label_for(el), text=text,
                   font_h=h, font_w=w, spacing=sp, n_lines=n_lines, along=fr.w,
                   align=align, orient=el.orient, elastic=elastic)
        it.legacy_chunks = legacy_chunks
        it.legacy_overflow = legacy_overflow
        it.base_font = (h, w, sp)
        it.fit_warning = None
        it.design_lines = n_lines
        it.u0, it.v0 = fr.x0, fr.y0
        it.A0 = fr.w
        it.pad_ratio = _ACCENT_RATIO if _has_upper_accent(text) else _OVERSHOOT_RATIO
        it.pad_up = it.pad_ratio * h
        if elastic:
            # Sin ^FB: la caja inicial es el texto real, hasta el borde útil.
            safe = _to_frame(self.safe, el.orient, self.W, self.H)
            need = text_width(text, w) if text.strip() else 1
            self._set_text_rect(it, fr.x0, fr.y0, max(1, min(need, safe.x1 - fr.x0)), n_lines)
        return it

    def _set_text_rect(self, it, u0, v0, along, n_lines):
        bh = (n_lines - 1) * (it.font_h + it.spacing) + it.font_h
        fr = Rect(u0, v0, u0 + along, v0 + bh)
        it.rect = _from_frame(fr, it.orient, self.W, self.H)
        it.along = along
        it.n_lines = n_lines

    def _obstacles(self, items, idx, soft=False):
        """Obstáculos para el texto idx. Con soft=True se omiten los textos aún
        no ajustados que ya se solapaban con este (se reacomodarán después)."""
        out = []
        me = items[idx].footprint()
        for j, other in enumerate(items):
            if j == idx or other.kind == "other" or (idx, j) in self.exempt:
                continue
            if other.kind == "text" and not other.text.strip():
                continue
            if soft and other.kind == "text" and not getattr(other, "fitted", False)                     and other.footprint().intersects(me):
                continue
            gap = 0 if other.kind == "qr" or (idx, j) in self.tight else self.gap
            out.append(other.footprint().inflate(gap))
        return out

    def _fit_text(self, items, idx, identity):
        it = items[idx]
        it.fitted = True
        if not it.text.strip():
            return
        W, H = self.W, self.H
        o = it.orient
        safe = _to_frame(self.safe, o, W, H)
        def frame_parts(rects):
            return [_to_frame(part, o, W, H) for r in rects for part in getattr(r, "parts", (r,))]
        obstacles = frame_parts(self._obstacles(items, idx))
        soft_obstacles = frame_parts(self._obstacles(items, idx, soft=True))
        u0, v0, A0 = it.u0, it.v0, it.A0
        n0 = it.design_lines
        h0, w0, sp0 = getattr(it, "base_font", (it.font_h, it.font_w, it.spacing))
        if h0 and h0 < self.min_text:
            # El diseño usa una letra menor que el mínimo legible configurado.
            up = self.min_text / h0
            h0, w0, sp0 = h0 * up, w0 * up, sp0 * up
        pad_ratio = getattr(it, "pad_ratio", _OVERSHOOT_RATIO)
        it.fit_warning = None
        words = set(it.text.split())

        def blocked(rect, obs=None):
            return any(rect.intersects(ob) for ob in (obstacles if obs is None else obs))

        def intervals(v_top, v_bot, obs=None):
            obs = obstacles if obs is None else obs
            cuts = sorted((ob.x0, ob.x1) for ob in obs if ob.y0 < v_bot and v_top < ob.y1)
            free, pos = [], safe.x0
            for c0, c1 in cuts:
                if c0 > pos:
                    free.append((pos, min(c0, safe.x1)))
                pos = max(pos, c1)
            if pos < safe.x1:
                free.append((pos, safe.x1))
            return [f for f in free if f[1] - f[0] > 1]

        def interval_at(v_top, v_bot, u, obs=None):
            for a, b in intervals(v_top, v_bot, obs):
                if a - 0.5 <= u < b:
                    return a, b
            return None

        def best_interval(v_top, v_bot, a0, b0, need=None):
            """Hueco libre de la franja: el más cercano a [a0, b0] donde quepa
            `need`; si ninguno alcanza, el más amplio."""
            free = intervals(v_top, v_bot)
            if not free:
                return None
            if need:
                fits = [f for f in free if f[1] - f[0] >= need]
                if fits:
                    return min(fits, key=lambda f: (max(f[0] - b0, a0 - f[1], 0),
                                                    -(min(f[1], b0) - max(f[0], a0))))
                return max(free, key=lambda f: f[1] - f[0])
            return max(free, key=lambda f: (min(f[1], b0) - max(f[0], a0), f[1] - f[0]))

        def free_down(a, b, v_top):
            limit = safe.y1
            for ob in obstacles:
                if ob.x0 < b and a < ob.x1 and ob.y0 >= v_top - 0.5:
                    limit = min(limit, ob.y0)
            return limit

        def free_up(a, b, v_bot):
            limit = safe.y0
            for ob in obstacles:
                if ob.x0 < b and a < ob.x1 and ob.y1 <= v_bot + 0.5:
                    limit = max(limit, ob.y1)
            return limit

        def try_scale(f, allow_break=False, far=False):
            h, w, sp = h0 * f, w0 * f, sp0 * f
            pitch = h + sp
            pad = pad_ratio * h

            def block(n):
                return (n - 1) * pitch + h

            def wrap(width):
                if width <= 1:
                    return None
                lines = wrap_text(it.text, width, w)
                if any(text_width(line, w) > width + 0.5 for line in lines):
                    return None   # ni siquiera un carácter cabe en ese ancho
                if not allow_break and any(" " not in line and line not in words for line in lines):
                    return None   # habría que partir una palabra
                return lines

            def place(how, u, v, width, n, lines):
                if it.elastic:
                    width = max(text_width(line, w) for line in lines)
                # El bloque ocupa solo las líneas que usa (la plantilla puede
                # reservar más; esa reserva no debe invadir ni salirse del área).
                return (how, dict(u=u, v=v, along=width, n=len(lines), lines=lines,
                                  h=h, w=w, sp=sp))

            v_home = min(max(v0, safe.y0 + pad), max(safe.y0 + pad, safe.y1 - block(n0)))
            base_w = A0 if not it.elastic else 0

            def widen(v, n):
                need = None
                if it.elastic or it.align == "L":
                    longest_word = max((text_width(wd, w) for wd in it.text.split()), default=1)
                    need = max(longest_word, text_width(it.text, w) / n)
                iv = best_interval(v - pad, v + block(n), u0, u0 + max(base_w, 1), need)
                if not iv:
                    return None
                a, b = iv
                if it.align == "C" and base_w:
                    center = u0 + base_w / 2
                    half = min(center - a, b - center)
                    return (a, b - a) if half * 2 < base_w else (center - half, half * 2)
                if it.align == "R" and base_w:
                    end = u0 + base_w if a < u0 + base_w <= b else b
                    return a, end - a
                start = u0 if a <= u0 < b else a
                if need and b - start < need:
                    # Retroceder el inicio lo justo para que quepa en el hueco.
                    start = max(a, b - need)
                return start, b - start

            def deepen(v, start, width, upward=True):
                bottom = free_down(start, start + width, v)
                n_down = int((bottom - v - h) // pitch) + 1 if bottom - v >= h else 0
                if not upward:
                    return v, n_down
                top = max(free_up(start, start + width, v + h), safe.y0) + pad
                n_all = int((bottom - top - h) // pitch) + 1 if bottom - top >= h else 0
                return (v, n_down) if n_down >= n_all else (top, n_all)

            def attempt(v, home):
                # (1) caja original (los textos que se solapaban en el diseño y
                #     aún no se ajustaron no la bloquean: se moverán ellos)
                if home and it.elastic:
                    iv = interval_at(v - pad, v + block(n0), u0, soft_obstacles)
                    if iv:
                        lines = wrap(iv[1] - u0)
                        if lines and len(lines) <= n0:
                            tight_w = max(text_width(line, w) for line in lines)
                            if not blocked(Rect(u0, v - pad, u0 + tight_w, v + block(len(lines))),
                                           soft_obstacles):
                                return place("original", u0, v, iv[1] - u0, n0, lines)
                elif home:
                    rect = Rect(u0, v - pad, u0 + A0, v + block(n0))
                    lines = wrap(A0)
                    if lines and len(lines) <= n0 and rect.inside(safe) \
                            and not blocked(rect, soft_obstacles):
                        return place("original", u0, v, A0, n0, lines)

                tag = "" if home else " y reubicado"
                strategies = ["widen", "deepen", "both"]
                if self.orientation == "vertical" or o in ("B", "R"):
                    strategies = ["deepen", "widen", "both"]
                for strat in strategies:
                    if strat == "widen":
                        res = widen(v, n0)
                        if res:
                            lines = wrap(res[1])
                            if lines and len(lines) <= n0:
                                box = Rect(res[0], v - pad, res[0] + res[1], v + block(len(lines)))
                                if box.inside(safe) and not blocked(box):
                                    return place("widen" + tag, res[0], v, res[1], n0, lines)
                    elif strat == "deepen":
                        if it.elastic:
                            iv = interval_at(v - pad, v + h, u0)
                            if not iv:
                                continue
                            start, width = u0, iv[1] - u0
                        else:
                            start, width = u0, A0
                            if blocked(Rect(start, v - pad, start + width, v + h)):
                                continue
                        top, n_avail = deepen(v, start, width, upward=home)
                        lines = wrap(width)
                        if lines and len(lines) <= n_avail:
                            return place("deepen" + tag, start, top, width, len(lines), lines)
                    else:
                        res = widen(v, 1)
                        if res:
                            top, n_avail = deepen(v, res[0], res[1], upward=home)
                            lines = wrap(res[1])
                            if lines and len(lines) <= n_avail:
                                return place("both" + tag, res[0], top, res[1], len(lines), lines)
                return None

            res = attempt(v_home, True)
            if res:
                return res
            # (5) reubicar: probar otras alturas libres, de la más cercana a la
            #     más lejana, antes de reducir la tipografía.
            # Solo en la vecindad: un valor no debe alejarse de su rótulo
            # (jerarquía visual). Si ahí no cabe, se reduce la tipografía.
            step = max(2.0, h / 6)
            reach = float("inf") if far else max(2.5 * h0, 0.12 * (safe.y1 - safe.y0))
            lo = max(safe.y0 + pad, v_home - reach)
            hi = min(safe.y1 - h, v_home + reach)
            offsets = []
            k = 1
            while v_home - k * step >= lo or v_home + k * step <= hi:
                for v in (v_home + k * step, v_home - k * step):
                    if lo <= v <= hi:
                        offsets.append(v)
                k += 1
            for v in offsets:
                res = attempt(v, False)
                if res:
                    return res
            return None

        # Escalas: primero redistribuir; luego reducir de a 6 % hasta el mínimo.
        min_f = min(1.0, self.min_text / h0) if h0 else 1.0
        scales = [1.0]
        while scales[-1] * 0.94 > min_f:
            scales.append(scales[-1] * 0.94)
        if scales[-1] > min_f:
            scales.append(min_f)

        chosen = None
        for f in scales:
            res = try_scale(f)
            if res:
                chosen = (f,) + res
                break
        if chosen is None:
            # Último recurso antes de avisar: reubicar en cualquier parte del área útil.
            for f in scales:
                res = try_scale(f, far=True)
                if res:
                    chosen = (f,) + res
                    break
        if chosen is None:
            res = try_scale(min_f, allow_break=True, far=True)
            if res:
                chosen = (min_f,) + res
                self.notes.append(f"«{it.label}»: se partió una palabra para que quepa.")

        if chosen is None:
            # No cabe: ubicar en el hueco más amplio a tamaño mínimo y avisar.
            f = min_f
            h, w = h0 * f, w0 * f
            pitch = h + sp0 * f
            v = min(max(v0, safe.y0), safe.y1 - h)
            iv = best_interval(v, v + h, u0, u0 + max(A0, 1)) or (u0, u0 + max(A0, 1))
            start, width = iv[0], iv[1] - iv[0]
            lines = wrap_text(it.text, width, w)
            room = max(int((free_down(start, start + width, v) - v - h) // pitch) + 1, 0)
            widest_word = max((text_width(wd, w) for wd in it.text.split()), default=0)
            if len(lines) <= room and widest_word > width:
                it.fit_warning = (
                    f"«{it.label}» no cabe a lo ancho: necesita {widest_word / self.dpmm:.1f} mm "
                    f"y solo hay {width / self.dpmm:.1f} mm libres "
                    f"(texto de {h / self.dpmm:.1f} mm de alto).")
            else:
                it.fit_warning = (
                    f"«{it.label}» no cabe: necesita {len(lines)} línea(s) de "
                    f"{h / self.dpmm:.1f} mm y solo hay espacio para {room} "
                    f"(ancho libre {width / self.dpmm:.1f} mm).")
            it.font_h, it.font_w, it.spacing = h, w, sp0 * f
            it.lines = lines
            self._set_text_rect(it, start, v, width, max(1, len(lines)))
            it.changed = True
            return

        f, how, p = chosen
        unchanged = (how == "original" and f == 1.0 and identity and not it.legacy_overflow)
        if unchanged and it.legacy_chunks is not None:
            # El comportamiento histórico corta cada NN caracteres: cada trozo
            # debe caber en su línea.
            limit = A0 if not it.elastic else safe.x1 - u0
            unchanged = all(text_width(c, it.font_w) <= limit for c in it.legacy_chunks)
        it.font_h, it.font_w, it.spacing = p["h"], p["w"], p["sp"]
        it.lines = p["lines"]
        it.pad_up = pad_ratio * p["h"]
        self._set_text_rect(it, p["u"], p["v"], p["along"], p["n"])
        it.changed = not unchanged
        if f < 1.0:
            self.notes.append(f"«{it.label}»: tipografía reducida al {f * 100:.0f} %.")
        elif how != "original":
            self.notes.append(f"«{it.label}»: {_HOW_LABELS.get(how.split(' ')[0], how)}"
                              f"{' y reubicado' if 'reubicado' in how else ''}.")

    # --------------------------------------------------------------- rígidos
    def _settle_rigid(self, items):
        rigid = [i for i, it in enumerate(items) if it.kind in ("qr", "barcode", "graphic", "box")]
        for i in rigid:
            it = items[i]
            r = it.rect
            dx = dy = 0
            if r.x0 < self.safe.x0:
                dx = self.safe.x0 - r.x0
            elif r.x1 > self.safe.x1:
                dx = self.safe.x1 - r.x1
            if r.y0 < self.safe.y0:
                dy = self.safe.y0 - r.y0
            elif r.y1 > self.safe.y1:
                dy = self.safe.y1 - r.y1
            if dx or dy:
                it.rect = Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
                it.fixed = False
        # QR en conflicto: reducir el módulo (sin bajar del mínimo) antes de mover nada.
        def qr_conflicts(i):
            q = items[i]
            if not q.rect.inside(self.safe):
                return True
            for j in rigid:
                if j != i and (i, j) not in self.exempt and \
                        q.footprint().intersects(items[j].footprint()):
                    return True
            return False

        for i in rigid:
            q = items[i]
            if q.kind != "qr":
                continue
            if not qr_conflicts(i):
                continue
            original = (q.qr_module, q.rect, q.quiet)
            solved = False
            for module in range(q.qr_module - 1, self.min_qr - 1, -1):
                size = q.qr_size * module
                r = q.place(size, size)
                dx = max(self.safe.x0 - r.x0, 0) + min(self.safe.x1 - r.x1, 0)
                dy = max(self.safe.y0 - r.y0, 0) + min(self.safe.y1 - r.y1, 0)
                q.rect = Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
                q.qr_module = module
                q.quiet = getattr(q, "quiet_modules", self.s.qr_quiet_modules) * module
                if not qr_conflicts(i):
                    solved = True
                    q.fixed = False
                    break
            if not solved:
                # Reducir no resuelve el choque: conservar el tamaño y dejar que
                # el desplazamiento (o la advertencia) se encargue.
                q.qr_module, q.rect, q.quiet = original
            if not q.fixed and q.qr_module != q.el.bq_mag:
                self.notes.append(f"Código QR: módulo de {q.qr_module / self.dpmm:.2f} mm "
                                  f"({q.qr_size}×{q.qr_size} módulos).")

        for i in rigid:
            it = items[i]
            if not it.rect.inside(self.safe):
                self.warnings.append(
                    f"El {it.label} ({it.rect.w / self.dpmm:.1f}×{it.rect.h / self.dpmm:.1f} mm) "
                    f"no cabe en el área útil "
                    f"({self.safe.w / self.dpmm:.1f}×{self.safe.h / self.dpmm:.1f} mm).")

        # Choques entre rígidos: desplazar el segundo si hay espacio
        for a_pos, i in enumerate(rigid):
            for j in rigid[a_pos + 1:]:
                if (i, j) in self.exempt:
                    continue
                a, b = items[i], items[j]
                gap = 0 if "qr" in (a.kind, b.kind) or (i, j) in self.tight else self.gap
                if not a.footprint().inflate(gap).intersects(b.footprint()):
                    continue
                if self._nudge(items, j, i, gap) or self._nudge(items, i, j, gap):
                    continue
                self.warnings.append(f"El {a.label} y el {b.label} se superponen; no hay espacio para separarlos.")

    def _nudge(self, items, move, keep, gap):
        a, b = items[keep].footprint().inflate(gap), items[move]
        fp = b.footprint()
        options = [
            (a.x1 - fp.x0, 0), (a.x0 - fp.x1, 0),
            (0, a.y1 - fp.y0), (0, a.y0 - fp.y1),
        ]
        options.sort(key=lambda d: abs(d[0]) + abs(d[1]))
        for dx, dy in options:
            new = Rect(b.rect.x0 + dx, b.rect.y0 + dy, b.rect.x1 + dx, b.rect.y1 + dy)
            if not new.inside(self.safe):
                continue
            trial = copy.copy(b)
            trial.rect = new
            ok = True
            for k, other in enumerate(items):
                if k == move or other.kind in ("text", "other") or (move, k) in self.exempt:
                    continue
                g = 0 if "qr" in (other.kind, b.kind) or (move, k) in self.tight else self.gap
                if trial.footprint().inflate(g).intersects(other.footprint()):
                    ok = False
                    break
            if ok:
                b.rect = new
                b.fixed = False
                return True
        return False

    def _final_check(self, items):
        for i, it in enumerate(items):
            if it.kind == "other" or (it.kind == "text" and not it.text.strip()):
                continue
            if not it.rect.inside(self.safe, tol=1):
                msg = f"«{it.label}» queda fuera del área imprimible." if it.kind == "text" \
                    else f"El {it.label} queda fuera del área imprimible."
                if msg not in self.warnings and not any(it.label in w for w in self.warnings):
                    self.warnings.append(msg)
            for j in range(i + 1, len(items)):
                other = items[j]
                if other.kind == "other" or (i, j) in self.exempt:
                    continue
                if other.kind == "text" and not other.text.strip():
                    continue
                if it.footprint().intersects(other.footprint()):
                    names = (it.label, other.label)
                    if not any(n in w for w in self.warnings for n in names):
                        self.warnings.append(f"«{names[0]}» y «{names[1]}» se superponen.")

    # ----------------------------------------------------------------- emisión
    def _emit(self, items):
        by_el = {id(it.el): it for it in items}
        segs = self._merge_segments(self.tpl.elements)
        skip = {id(el) for members in segs.values() for el in members[1:]}
        out = []
        for item in self.tpl.body_items:
            if isinstance(item, str):
                cmd = item[1:3].upper()
                if cmd == "PW":
                    out.append(f"^PW{self.W}")
                elif cmd == "LL":
                    out.append(f"^LL{self.H}")
                elif cmd == "LH":
                    out.append("^LH0,0")
                else:
                    out.append(item)
                continue
            if id(item) in skip:
                continue
            it = by_el.get(id(item))
            if it is None:
                continue
            out.append(self._emit_item(it) + "\n")
        body = "".join(out)
        if not re.search(r"\^PW", body, re.IGNORECASE):
            body = body.replace("^XA", f"^XA^PW{self.W}^LL{self.H}", 1)
        return self.tpl.header + body + self.tpl.trailer

    def _emit_item(self, it):
        el = it.el
        r = it.rect
        x, y = int(round(r.x0)), int(round(r.y0))
        if it.kind == "text":
            h = max(1, int(round(it.font_h)))
            w = max(1, int(round(it.font_w)))
            sp = int(round(it.spacing))
            lines = it.lines or [it.text]
            n = max(len(lines), it.n_lines if not it.elastic else 1)
            width = int(math.ceil(it.along)) + 1
            # ^FO es la esquina superior izquierda del campo ya rotado: se calcula
            # con el ancho emitido para que el inicio del texto no se desplace.
            fr = _to_frame(it.rect, it.orient, self.W, self.H)
            page = _from_frame(Rect(fr.x0, fr.y0, fr.x0 + width, fr.y1), it.orient, self.W, self.H)
            x, y = int(round(page.x0)), int(round(page.y0))
            data = "\\&".join(_encode_fd(line, el.ci) for line in lines)
            return (f"{el.ci_token}^FO{x},{y}^A{el.font}{it.orient},{h},{w}"
                    f"^FB{width},{n},{sp},{it.align},0^FH_^FD{data}^FS")
        if it.kind == "qr" and el.kind == "aztec":
            params = list(el.bo) + [""] * max(0, 2 - len(el.bo))
            params[1] = str(it.qr_module)
            fh, filled = self._fill_escaped(el)
            return f"^FO{x},{y}^BO{','.join(params)}{fh}^FD{filled}^FS"
        if it.kind == "qr":
            fh, filled = self._fill_escaped(el)
            return f"^FO{x},{max(0, y - _QR_FO_OFFSET)}^BQN,2,{it.qr_module}{fh}^FD{filled}^FS"
        if it.kind == "barcode":
            bc = list(el.bc)
            bc[1] = str(it.bc_height)
            fh, filled = self._fill_escaped(el)
            ratio = el.by[1]
            ratio_txt = f"{ratio:g}"
            return (f"^BY{it.bc_module},{ratio_txt},{it.bc_height}^FO{x},{y}"
                    f"^BC{','.join(bc).rstrip(',')}{fh}^FD{filled}^FS")
        if it.kind == "graphic":
            total, bpr, data = el.gf
            w0, h0 = bpr * 8, total // bpr
            crop = getattr(el, "gf_crop", (0, 0, w0, h0))
            if it.gf_size == (w0, h0) and crop == (0, 0, w0, h0):
                return f"^FO{x},{y}{el.gf_token}^FS"
            # El redimensionado es costoso: se cachea en la plantilla analizada.
            cache = el.__dict__.setdefault("_gf_cache", {})
            key = (it.gf_size, crop)
            if key not in cache:
                bitmap, rows = gf_decode(data, total, bpr)
                new, nbpr, nrows = gf_resize(bitmap, bpr, rows, it.gf_size[0], it.gf_size[1], crop)
                cache[key] = (new, nbpr, nrows, gf_encode_ascii(new, nbpr, nrows))
            new, nbpr, nrows, encoded = cache[key]
            ntotal = nbpr * nrows
            return f"^FO{x},{y}^GFA,{ntotal},{ntotal},{nbpr},{encoded}^FS"
        if it.kind == "box":
            w, h, t = it.gb_dims
            _, _, _, color, rnd = el.gb
            if el.gb[1] <= el.gb[2]:
                h = 0
            elif el.gb[0] <= el.gb[2]:
                w = 0
            return f"^FO{x},{y}^GB{w},{h},{t},{color},{rnd}^FS"
        # Otros: conservar comandos con el origen trasladado
        return f"^FO{x},{y}" + "".join(t.rstrip("\r\n") for t in el.tokens) + "^FS"


def set_print_quantity(zpl, copies):
    """Fija la cantidad de ^PQ en el último formato (^XA…^XZ), que es la etiqueta:
    el ZPL se envía una vez y la impresora repite las copias (el bloque de
    configuración previo, con ^JUS, ya no se reenvía por cada copia). Conserva el
    resto de parámetros de ^PQ; si no hay ^PQ lo añade antes del ^XZ final."""
    copies = int(copies)
    starts = list(re.finditer(r"\^XA", zpl, re.IGNORECASE))
    if not starts:
        return zpl
    start = starts[-1].start()
    block = zpl[start:]
    pq = re.search(r"\^PQ(\d*)", block, re.IGNORECASE)
    if pq:
        block = block[:pq.start(1)] + str(copies) + block[pq.end(1):]
    else:
        end = re.search(r"\^XZ", block, re.IGNORECASE)
        pos = end.start() if end else len(block)
        block = block[:pos] + f"^PQ{copies}" + block[pos:]
    return zpl[:start] + block


def compose(template_zpl, template_name, resolver, width_mm=None, height_mm=None,
            dpi=203, settings=None, labeler=None, parsed=None):
    """Compone la etiqueta. `resolver(var, max_len)` devuelve el valor de una
    variable de la plantilla. Si no se da tamaño, usa el de la plantilla."""
    settings = settings or LayoutSettings()
    try:
        tpl = parsed or parse_template(template_zpl, template_name)
    except Exception as exc:  # plantilla no analizable: comportamiento histórico
        zpl = legacy_fill(template_zpl, resolver)
        return LayoutResult(zpl, "sin_analisis", [f"No se pudo analizar la plantilla: {exc}"],
                            width_mm or 0, height_mm or 0, dpi)
    if width_mm is None or height_mm is None:
        width_mm, height_mm = tpl.size_mm
    composer = _Composer(tpl, resolver, width_mm, height_mm, dpi, settings, labeler)
    composer.source_zpl = template_zpl
    result = composer.compose()
    if tpl.size_note:
        result.notes.insert(0, tpl.size_note)
    return result


# =============================================================================
# ASOCIACIÓN TAMAÑO <-> PLANTILLAS
# =============================================================================

def templates_for_size(size_mm, template_sizes):
    """Plantillas aplicables a un tamaño: misma orientación y medida más cercana.
    `template_sizes` es {nombre: (ancho_mm, alto_mm)}."""
    target = orientation_of(*size_mm)
    scored = []
    for name, (w, h) in template_sizes.items():
        if orientation_of(w, h) != target:
            continue
        score = abs(math.log(size_mm[0] / w)) + abs(math.log(size_mm[1] / h))
        scored.append((score, name))
    if not scored:
        return []
    best = min(s for s, _ in scored)
    return sorted(name for s, name in scored if s <= best + 0.15)
