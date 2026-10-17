"""Parseo de plantillas .prn y relleno de variables con escape ^FH/^CI
(un dato del Excel nunca inyecta comandos ZPL).

Parte del motor de ajuste (label_layout.py), que reexporta estos nombres."""

import re
from dataclasses import dataclass, field


# =============================================================================
# PARSEO DE PLANTILLAS
# =============================================================================

_PLACEHOLDER_RE = re.compile(r"\[([^\]]+)\](\d+)?")
_SEGMENT_RE = re.compile(r"(?i)^vlscampo(\d+)([a-z])$")
_SIZE_IN_NAME_RE = re.compile(r"(\d{2,3})\s*[xX×]\s*(\d{2,3})")


@dataclass
class Element:
    kind: str                    # text | qr | barcode | graphic | box | other
    index: int
    origin: str = "FO"
    x: int = 0
    y: int = 0
    tokens: list = field(default_factory=list)
    # texto
    font: str = "0"
    orient: str = "N"
    font_h: int = 0
    font_w: int = 0
    fb: tuple = None             # (ancho, líneas, espaciado, alineación, sangría)
    fh: str = None               # indicador ^FH (None si no hay ^FH)
    fd: str = ""
    # código de barras
    by: tuple = (2, 3.0, 10)
    bc: list = None
    bq_mag: int = 2
    ci: int = 0                  # codificación vigente al imprimir este campo
    ci_token: str = ""           # ^CI propio del campo (se reemite)
    # gráfico
    bo: list = None              # parámetros de ^BO (Aztec)
    gf: tuple = None             # (total, bpr, data)
    # recuadro
    gb: tuple = None             # (w, h, t, color, round)
    group: list = None           # índices de segmentos fusionados (vlsCampo3A/B/C)


@dataclass
class ParsedTemplate:
    name: str
    header: str
    body_items: list             # str (comandos globales) o Element
    trailer: str
    elements: list
    pw: int
    ll: int
    lh: tuple
    ci: int
    size_mm: tuple
    size_source: str
    size_note: str = ""

    @property
    def design_dpmm(self):
        return (self.pw / self.size_mm[0], self.ll / self.size_mm[1])


def template_size_mm(name, pw, ll):
    """Tamaño físico de la plantilla. El nombre del archivo manda; ^PW/^LL
    definen la orientación y se usan si el nombre no trae medidas."""
    match = _SIZE_IN_NAME_RE.search(name or "")
    by_dots = (round(pw / 8.0, 1), round(ll / 8.0, 1)) if pw and ll else None
    if match:
        a, b = int(match.group(1)), int(match.group(2))
        if pw and ll and pw != ll and a != b:
            w, h = (max(a, b), min(a, b)) if pw > ll else (min(a, b), max(a, b))
        else:
            w, h = a, b
        note = ""
        if by_dots and (abs(by_dots[0] - w) > 3 or abs(by_dots[1] - h) > 3):
            note = (f"Tamaño tomado del nombre ({w}×{h} mm); ^PW/^LL indican "
                    f"{by_dots[0]:g}×{by_dots[1]:g} mm a 203 dpi.")
        return (w, h), "nombre", note
    if by_dots:
        return by_dots, "^PW/^LL", ""
    return (102, 102), "por defecto", "La plantilla no indica su tamaño; se asume 102×102 mm."


def _int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_font(token, el):
    # ^A0N,22,21  ^A0B,41,41  ^A0,30,30
    body = token[2:]
    el.font = body[:1] or "0"
    rest = body[1:]
    orient = "N"
    if rest[:1].upper() in "NRIB" and rest[:1]:
        orient = rest[:1].upper()
        rest = rest[1:]
    parts = rest.lstrip(",").split(",") if rest else []
    h = _int(parts[0], 0) if parts else 0
    w = _int(parts[1], 0) if len(parts) > 1 else 0
    el.orient = orient
    el.font_h = h or 30
    el.font_w = w or el.font_h


def _parse_fb(token):
    parts = (token[3:].strip().split(",") + [""] * 5)[:5]
    width = _int(parts[0], 0)
    lines = max(1, _int(parts[1], 1))
    spacing = _int(parts[2], 0)
    align = (parts[3].strip()[:1] or "L").upper()
    hang = _int(parts[4], 0)
    return (width, lines, spacing, align, hang)


_FIELD_CMDS = {"FB", "FH", "FD", "FR", "FN", "FV", "FX", "FW", "FP", "BQ", "BC", "BY",
               "B3", "BE", "BU", "B7", "BX", "GF", "GB", "GC", "GD", "GE", "CI", "TB"}


def parse_template(zpl, name=""):
    blocks = list(re.finditer(r"\^XA", zpl, re.IGNORECASE))
    if not blocks:
        raise ValueError("La plantilla no contiene ^XA.")
    start = blocks[-1].start()
    end_match = re.search(r"\^XZ", zpl[start:], re.IGNORECASE)
    end = start + end_match.end() if end_match else len(zpl)
    header, body, trailer = zpl[:start], zpl[start:end], zpl[end:]

    ci_values = re.findall(r"\^CI(\d+)", header)
    ci = int(ci_values[-1]) if ci_values else 0

    tokens = re.findall(r"[\^~][^\^~]*", body, re.DOTALL)
    items = []
    elements = []
    lh = (0, 0)
    pw = ll = 0
    by = (2, 3.0, 10)
    pending_font = None
    current = None

    def close():
        nonlocal current
        if current is not None:
            current.ci = ci
            _classify(current)
            elements.append(current)
            items.append(current)
            current = None

    for tok in tokens:
        cmd = tok[1:3].upper()
        # Un comando que no pertenece a un campo cierra el campo abierto
        # (plantillas con ^FD sin ^FS).
        if current is not None and tok[0] == "^" and cmd not in _FIELD_CMDS \
                and not (tok[1:2].upper() in ("A", "B")) and cmd not in ("FO", "FT", "FS"):
            close()
        if cmd in ("FO", "FT"):
            close()
            xy = tok[3:].strip().split(",")
            current = Element(kind="other", index=len(elements), origin=cmd,
                              x=_int(xy[0]) + lh[0],
                              y=_int(xy[1] if len(xy) > 1 else 0) + lh[1],
                              by=by)
            if pending_font:
                _parse_font(pending_font, current)
                current.tokens.append(pending_font)
                pending_font = None
            continue
        if cmd == "FS":
            close()
            continue
        if cmd == "CI":
            ci = _int(tok[3:].split(",")[0], ci)
            if current is not None:
                current.ci_token = tok.rstrip("\r\n")
            else:
                items.append(tok)
            continue
        if cmd == "BY":
            p = (tok[3:].strip().split(",") + ["", "", ""])[:3]
            by = (_int(p[0], 2) or 2, float(p[1] or 3.0), _int(p[2], 10) or 10)
            if current is not None:
                current.by = by
            else:
                items.append(tok)
            continue
        if current is None:
            if cmd == "LH":
                p = tok[3:].strip().split(",")
                lh = (_int(p[0]), _int(p[1] if len(p) > 1 else 0))
            elif cmd == "PW":
                pw = _int(tok[3:])
            elif cmd == "LL":
                ll = _int(tok[3:])
            elif tok[1:2].upper() == "A" and tok[0] == "^" and cmd not in ("A@",):
                pending_font = tok
                continue
            items.append(tok)
            continue
        current.tokens.append(tok)
        if tok[1:2].upper() == "A" and tok[0] == "^" and cmd != "A@":
            _parse_font(tok, current)
        elif cmd == "FB":
            current.fb = _parse_fb(tok)
        elif cmd == "FH":
            current.fh = tok[3:4] or "_"
        elif cmd == "FD":
            current.fd = tok[3:].rstrip("\r\n")
        elif cmd == "BQ":
            p = (tok[3:].split(",") + ["", "", ""])[:3]
            current.bq_mag = _int(p[2], 2) or 2
        elif cmd == "BC":
            current.bc = (tok[3:].split(",") + [""] * 6)[:6]
        elif cmd == "BO":
            current.bo = tok[3:].strip().split(",")
            current.bq_mag = _int(current.bo[1] if len(current.bo) > 1 else 2, 2) or 2
        elif cmd == "GF":
            p = tok[3:].split(",", 4)
            if len(p) >= 5:
                # ^GFA,<bytes transmitidos>,<bytes de la imagen>,<bytes por fila>,<datos>
                current.gf = (_int(p[2]) or _int(p[1]), _int(p[3]), p[4])
                current.gf_token = tok.rstrip("\r\n")
        elif cmd == "GB":
            p = (tok[3:].strip().split(",") + [""] * 5)[:5]
            current.gb = (_int(p[0], 1), _int(p[1], 1), _int(p[2], 1) or 1,
                          (p[3].strip() or "B")[:1], _int(p[4], 0))
    close()

    size_mm, source, note = template_size_mm(name, pw, ll)
    if not pw:
        pw = int(round(size_mm[0] * 8))
    if not ll:
        ll = int(round(size_mm[1] * 8))
    return ParsedTemplate(name=name, header=header, body_items=items, trailer=trailer,
                          elements=elements, pw=pw, ll=ll, lh=lh, ci=ci,
                          size_mm=size_mm, size_source=source, size_note=note)


def _classify(el):
    cmds = {t[1:3].upper() for t in el.tokens}
    if "BQ" in cmds:
        el.kind = "qr"
    elif "BO" in cmds:
        el.kind = "aztec"
    elif "BC" in cmds:
        el.kind = "barcode"
    elif "GF" in cmds and el.gf:
        el.kind = "graphic"
    elif "GB" in cmds and el.gb:
        el.kind = "box"
    elif "FD" in cmds and el.font_h and not any(c.startswith("B") for c in cmds):
        el.kind = "text"
    else:
        el.kind = "other"


# =============================================================================
# RELLENO DE DATOS
# =============================================================================

def _decode_fh(text, indicator, ci):
    if not indicator:
        return text
    pattern = re.compile(re.escape(indicator) + r"([0-9A-Fa-f]{2})")
    if not pattern.search(text):
        return text
    raw = bytearray()
    pos = 0
    for m in pattern.finditer(text):
        raw.extend(text[pos:m.start()].encode("utf-8"))
        raw.append(int(m.group(1), 16))
        pos = m.end()
    raw.extend(text[pos:].encode("utf-8"))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(_ci_codec(ci), errors="replace")


def _ci_codec(ci):
    """Página de códigos que usa la impresora para cada ^CI."""
    if ci in (28, 29, 30):
        return "utf-8"
    if ci == 27:
        return "cp1252"
    return "cp850"


def _encode_fd(text, ci, indicator="_"):
    """Texto -> datos ^FD para un campo con ^FH<indicator> (escapa ^ ~ \\, el
    propio indicador, caracteres de control y no-ASCII)."""
    out = []
    encoding = _ci_codec(ci)
    for ch in text:
        if ch in "^~\\" or ch == indicator or ord(ch) < 32 or ord(ch) > 126:
            data = ch.encode(encoding, errors="replace")
            out.append("".join(f"{indicator}{b:02X}" for b in data))
        else:
            out.append(ch)
    return "".join(out)


def _fill_fd(fd, fh, ci, resolver):
    """Rellena las [variables] de los datos de un ^FD escapando cada valor con
    el indicador ^FH del campo y la página de códigos de su ^CI: un dato del
    Excel nunca inyecta comandos ZPL ni rompe las tildes.
    Devuelve (comando ^FH, datos). Si el campo no tenía ^FH hay que añadir el
    devuelto (^FH_); por eso los "_" del texto fijo se escapan también."""
    indicator = fh or "_"

    def literal(text):
        return text if fh else text.replace("_", "_5F")

    pieces = []
    pos = 0
    for m in _PLACEHOLDER_RE.finditer(fd):
        pieces.append(literal(fd[pos:m.start()]))
        max_len = int(m.group(2)) if m.group(2) else None
        value = resolver(m.group(1), max_len)
        pieces.append(_encode_fd("" if value is None else str(value), ci, indicator))
        pos = m.end()
    pieces.append(literal(fd[pos:]))
    return f"^FH{indicator}", "".join(pieces)


_LEGACY_FD_CMDS = ("FD", "FV")
_LEGACY_FIELD_RESET = ("FO", "FT", "FS", "XA", "XZ")


def legacy_fill(zpl, resolver):
    """Comportamiento histórico: reemplaza [variables] (con segmentación ]NN)
    y cierra ^FD sin ^FS. Se usa cuando la plantilla ya cumple en su tamaño.
    Los valores se escapan igual que en el modo adaptado (ver _fill_fd)."""
    ci = 0
    fh = None
    out = []
    # Cada trozo empieza por ^ o ~ (salvo el primero); unirlos devuelve el original.
    for tok in re.split(r"(?=[\^~])", zpl):
        cmd = tok[1:3].upper() if tok[:1] == "^" else ""
        if cmd in _LEGACY_FIELD_RESET:
            fh = None
        elif cmd == "CI":
            ci = _int(tok[3:].split(",")[0], ci)
        elif cmd == "FH":
            fh = tok[3:4] if tok[3:4].strip() else "_"

        if not _PLACEHOLDER_RE.search(tok):
            out.append(tok)
        elif cmd in _LEGACY_FD_CMDS:
            fh_cmd, data = _fill_fd(tok[3:], fh, ci, resolver)
            out.append(("" if fh else fh_cmd) + tok[:3] + data)
        else:
            # Variable fuera de ^FD (plantilla mal formada, p. ej. "^FH\^[var]"):
            # sin ^FH no hay escape posible. Solo pasan caracteres inocuos y, si la
            # variable va pegada a ^ o ~, se omite: el dato sería el nombre del comando.
            def stripped(m):
                if m.start() <= 1 and tok[:1] in "^~":
                    return ""
                max_len = int(m.group(2)) if m.group(2) else None
                value = resolver(m.group(1), max_len)
                return re.sub(r"[^A-Za-z0-9 .,:;/\-]", "", "" if value is None else str(value))
            out.append(_PLACEHOLDER_RE.sub(stripped, tok))
    zpl = "".join(out)
    lines = zpl.split("\n")
    for i, line in enumerate(lines):
        if "^FD" in line and "^FS" not in line:
            lines[i] = line.rstrip("\r\n") + "^FS"
    return "\n".join(lines)
