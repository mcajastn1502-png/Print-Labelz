"""Helpers de calibración contra Labelary (solo desarrollo)."""
import time, io, hashlib, os, json
import requests
from PIL import Image, ImageOps

CACHE = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE, exist_ok=True)
_last = [0.0]


def render(zpl, w_in=4, h_in=4, dpmm=8):
    key = hashlib.sha1(f"{zpl}|{w_in}|{h_in}|{dpmm}".encode()).hexdigest()
    path = os.path.join(CACHE, key + ".png")
    if not os.path.exists(path):
        for attempt in range(6):
            wait = 0.4 - (time.time() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
            r = requests.post(
                f"https://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{w_in}x{h_in}/0/",
                data=zpl.encode("utf-8"), headers={"Accept": "image/png"}, timeout=30)
            if r.status_code == 200:
                open(path, "wb").write(r.content)
                break
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return Image.open(path).convert("L")


def bbox(img):
    """(x0, y0, x1, y1) exclusivo de los píxeles negros."""
    inv = ImageOps.invert(img).point(lambda v: 255 if v > 128 else 0)
    return inv.getbbox()
