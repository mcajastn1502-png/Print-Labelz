"""Métricas medidas contra Labelary: ancho de la fuente ^A0, tamaño de QR/Aztec/Code128
y codificación/redimensionado de gráficos ^GF. No "corregir" estas constantes a ojo.

Parte del motor de ajuste (label_layout.py), que reexporta estos nombres."""

import base64
import functools
import math
import unicodedata
import zlib


# =============================================================================
# MÉTRICAS MEDIDAS (fuente ^A0, Labelary)
# =============================================================================

# Avance por carácter en "em" del parámetro de ANCHO de ^A0 (el alto no influye).
_A0_ADVANCE = {
    ' ': 0.295, '!': 0.295, '"': 0.479, '#': 0.479, '$': 0.479, '%': 0.903,
    '&': 0.608, "'": 0.295, '(': 0.295, ')': 0.295, '*': 0.479, '+': 0.903,
    ',': 0.295, '-': 0.903, '.': 0.295, '/': 0.295, '0': 0.479, '1': 0.479,
    '2': 0.479, '3': 0.479, '4': 0.479, '5': 0.479, '6': 0.479, '7': 0.479,
    '8': 0.479, '9': 0.479, ':': 0.295, ';': 0.295, '<': 0.996, '=': 0.903,
    '>': 0.996, '?': 0.442, '@': 0.903, 'A': 0.553, 'B': 0.553, 'C': 0.535,
    'D': 0.59, 'E': 0.498, 'F': 0.498, 'G': 0.59, 'H': 0.608, 'I': 0.276,
    'J': 0.442, 'K': 0.553, 'L': 0.479, 'M': 0.756, 'N': 0.608, 'O': 0.572,
    'P': 0.553, 'Q': 0.572, 'R': 0.59, 'S': 0.535, 'T': 0.498, 'U': 0.608,
    'V': 0.535, 'W': 0.812, 'X': 0.553, 'Y': 0.553, 'Z': 0.498, '[': 0.295,
    '\\': 0.756, ']': 0.295, '^': 0.756, '_': 0.756, '`': 0.295, 'a': 0.461,
    'b': 0.498, 'c': 0.442, 'd': 0.498, 'e': 0.479, 'f': 0.276, 'g': 0.498,
    'h': 0.498, 'i': 0.258, 'j': 0.258, 'k': 0.442, 'l': 0.258, 'm': 0.756,
    'n': 0.498, 'o': 0.479, 'p': 0.498, 'q': 0.498, 'r': 0.332, 's': 0.424,
    't': 0.276, 'u': 0.498, 'v': 0.442, 'w': 0.664, 'x': 0.442, 'y': 0.442,
    'z': 0.387, '{': 0.498, '|': 0.498, '}': 0.498, '~': 0.756,
}
_A0_DEFAULT_ADVANCE = 0.756          # caracteres no medidos: ancho de "M"
_TEXT_SAFETY = 1.04                  # holgura sobre el ancho medido
_CAP_RATIO = 0.75                    # línea base a 0.75·alto desde el tope de celda
_ACCENT_RATIO = 0.22                 # tilde de mayúsculas por encima de la celda
_OVERSHOOT_RATIO = 0.03              # letras redondas (O, G, Q) sobresalen del tope
_QR_FO_OFFSET = 10                   # ^BQ con ^FO dibuja el símbolo 10 puntos abajo
_QR_FT_EXTRA_MODULES = 3             # ^BQ con ^FT: tope = y - (módulos+3)·mag


def _char_advance(ch):
    adv = _A0_ADVANCE.get(ch)
    if adv is not None:
        return adv
    base = unicodedata.normalize("NFD", ch)[:1]
    return _A0_ADVANCE.get(base, _A0_DEFAULT_ADVANCE)


@functools.lru_cache(maxsize=8192)
def _text_em(text):
    return sum(_char_advance(c) for c in text)


def text_width(text, font_w):
    """Ancho estimado (en puntos) de una línea en ^A0 con ancho de fuente font_w."""
    if not text:
        return 0
    return _text_em(text) * font_w * _TEXT_SAFETY + 1


def _has_upper_accent(text):
    return any(c.isupper() and ord(c) > 127 for c in text)


def wrap_text(text, max_width, font_w):
    """Ajuste por palabras sin abreviar. Si una palabra no cabe sola, se parte
    por caracteres (no se elimina nada)."""
    return list(_wrap_cached(str(text), round(float(max_width), 2), round(float(font_w), 4)))


@functools.lru_cache(maxsize=16384)
def _wrap_cached(text, max_width, font_w):
    lines = []
    for paragraph in str(text).split("\n"):
        words = paragraph.split()
        if not words:
            continue
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if text_width(candidate, font_w) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            # Palabra sola demasiado larga: partir por caracteres.
            while text_width(word, font_w) > max_width:
                cut = 1
                while cut < len(word) and text_width(word[:cut + 1], font_w) <= max_width:
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return tuple(lines)


# =============================================================================
# QR Y CODE128
# =============================================================================

# Bits de datos por versión (1..25) y nivel de corrección.
_QR_DATA_BITS = {
    'L': [152, 272, 440, 640, 864, 1088, 1248, 1552, 1856, 2192, 2592, 2960, 3424, 3688,
          4184, 4712, 5176, 5768, 6360, 6888, 7456, 8048, 8752, 9392, 10208],
    'M': [128, 224, 352, 512, 688, 864, 992, 1232, 1456, 1728, 2032, 2320, 2672, 2920,
          3320, 3624, 4056, 4504, 5016, 5352, 5712, 6256, 6880, 7312, 8000],
    'Q': [104, 176, 272, 384, 496, 608, 704, 880, 1056, 1232, 1440, 1648, 1952, 2088,
          2360, 2600, 2936, 3176, 3560, 3880, 4096, 4544, 4912, 5312, 5744],
    'H': [72, 128, 208, 288, 368, 480, 528, 688, 800, 976, 1120, 1264, 1440, 1576,
          1784, 2024, 2264, 2504, 2728, 3080, 3248, 3536, 3712, 4112, 4304],
}
_QR_ALNUM = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:")


def qr_modules(payload, ecc="M"):
    """Módulos por lado del QR que generará ^BQ en modo automático."""
    ecc = ecc if ecc in _QR_DATA_BITS else "M"
    if payload and payload.isdigit():
        mode, n = "N", len(payload)
        data_bits = 10 * (n // 3) + (4 if n % 3 == 1 else 7 if n % 3 == 2 else 0)
    elif payload and all(c in _QR_ALNUM for c in payload):
        mode, n = "A", len(payload)
        data_bits = 11 * (n // 2) + 6 * (n % 2)
    else:
        mode, n = "B", len(payload.encode("utf-8"))
        data_bits = 8 * n
    cci = {"N": (10, 12), "A": (9, 11), "B": (8, 16)}[mode]
    for version, capacity in enumerate(_QR_DATA_BITS[ecc], start=1):
        bits = 4 + cci[0 if version <= 9 else 1] + data_bits
        if bits <= capacity:
            return 17 + 4 * version
    return None


def _split_qr_data(fd):
    """'LA,12345' -> ('L', '12345')."""
    if len(fd) >= 3 and fd[2] == "," and fd[0].upper() in "HQML":
        return fd[0].upper(), fd[3:]
    return "M", fd


# Módulos por lado de ^BO (Aztec) según la longitud del dato, medidos en
# Labelary con el peor caso entre dígitos, mayúsculas y texto mixto.
_AZTEC_SIZES = [(8, 15), (20, 19), (34, 23), (50, 27), (60, 31), (85, 37),
                (110, 41), (130, 45)]


def aztec_modules(data):
    n = len(data.encode("utf-8"))
    for limit, modules in _AZTEC_SIZES:
        if n <= limit:
            return modules
    return 45 + 4 * int(math.ceil((n - 130) / 20.0))


def code128_modules(data):
    """Ancho en módulos de ^BC en modo N (subconjunto B)."""
    return 11 * len(data) + 35


def _barcode_text_height(module):
    return int(math.ceil(7.5 * module + 6))


# =============================================================================
# GRÁFICOS ^GF
# =============================================================================

def _gf_decode_ascii(data, bpr, rows):
    row_len = bpr * 2
    out_rows = []
    current = []
    i = 0
    repeat = 0
    prev = "0" * row_len
    while i < len(data) and len(out_rows) < rows:
        ch = data[i]
        i += 1
        if "G" <= ch <= "Y":
            repeat += ord(ch) - ord("G") + 1
            continue
        if "g" <= ch <= "z":
            repeat += (ord(ch) - ord("g") + 1) * 20
            continue
        if ch in ",!:":
            if ch == ":":
                row = prev
            else:
                fill = "0" if ch == "," else "F"
                row = "".join(current) + fill * (row_len - len(current))
            out_rows.append(row[:row_len])
            prev = out_rows[-1]
            current = []
            repeat = 0
            continue
        if ch.upper() in "0123456789ABCDEF":
            current.extend([ch.upper()] * (repeat or 1))
            repeat = 0
            while len(current) >= row_len and len(out_rows) < rows:
                out_rows.append("".join(current[:row_len]))
                prev = out_rows[-1]
                current = current[row_len:]
    if current and len(out_rows) < rows:
        out_rows.append("".join(current).ljust(row_len, "0"))
    while len(out_rows) < rows:
        out_rows.append("0" * row_len)
    return bytes.fromhex("".join(out_rows))


def gf_decode(data, total, bpr):
    rows = total // bpr if bpr else 0
    data = data.strip()
    if data.startswith(":Z64:") or data.startswith(":B64:"):
        payload = data[5:].split(":")[0]
        raw = base64.b64decode(payload)
        if data.startswith(":Z64:"):
            raw = zlib.decompress(raw)
        return raw[:rows * bpr].ljust(rows * bpr, b"\x00"), rows
    return _gf_decode_ascii(data, bpr, rows), rows


def _rle_count(n):
    out = []
    while n >= 400:
        out.append("z")
        n -= 400
    if n >= 20:
        out.append(chr(ord("g") + n // 20 - 1))
        n %= 20
    if n:
        out.append(chr(ord("G") + n - 1))
    return "".join(out)


def gf_encode_ascii(bitmap, bpr, rows):
    """Codifica con la compresión ASCII estándar de ZPL (sin CRC)."""
    out = []
    prev = None
    for r in range(rows):
        row = bitmap[r * bpr:(r + 1) * bpr].hex().upper()
        if row == prev:
            out.append(":")
            continue
        prev = row
        stripped = row.rstrip("0")
        encoded = []
        i = 0
        while i < len(stripped):
            j = i
            while j < len(stripped) and stripped[j] == stripped[i]:
                j += 1
            run = j - i
            encoded.append((_rle_count(run) if run > 1 else "") + stripped[i])
            i = j
        if len(stripped) < len(row):
            encoded.append(",")
        out.append("".join(encoded))
    return "".join(out)


def _graphic_ink_box(el):
    """Caja (x0, y0, x1, y1) con tinta dentro del mapa de bits; se cachea en el elemento."""
    cached = getattr(el, "_ink_box", False)
    if cached is not False:
        return cached
    box = None
    try:
        from PIL import Image
        total, bpr, data = el.gf
        bitmap, rows = gf_decode(data, total, bpr)
        img = Image.frombytes("1", (bpr * 8, rows), bitmap)   # 1 = tinta
        box = img.getbbox()
    except Exception:
        box = None
    el._ink_box = box
    return box


def gf_resize(bitmap, bpr, rows, new_w, new_h, crop=None):
    """Recorta (opcional) y redimensiona un mapa de bits 1-bit (1 = negro)."""
    from PIL import Image
    width = bpr * 8
    img = Image.frombytes("1", (width, rows), bytes(b ^ 0xFF for b in bitmap))
    if crop:
        img = img.crop(crop)
    # BOX promedia la cobertura de cada punto; el umbral generoso conserva
    # trazos de 1 punto (líneas punteadas, letras finas del logotipo).
    img = img.convert("L").resize((max(1, new_w), max(1, new_h)), Image.BOX)
    img = img.point(lambda v: 0 if v < 170 else 255).convert("1")
    new_bpr = (img.width + 7) // 8
    padded = Image.new("1", (new_bpr * 8, img.height), 1)
    padded.paste(img, (0, 0))
    raw = bytes(b ^ 0xFF for b in padded.tobytes())
    return raw, new_bpr, img.height
