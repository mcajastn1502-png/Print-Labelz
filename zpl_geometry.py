"""Rectángulos y cambio de marco según la orientación del campo (N/R/I/B).

Parte del motor de ajuste (label_layout.py), que reexporta estos nombres."""

import math
from dataclasses import dataclass


# =============================================================================
# RECTÁNGULOS
# =============================================================================

@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def w(self):
        return self.x1 - self.x0

    @property
    def h(self):
        return self.y1 - self.y0

    def inflate(self, d):
        return Rect(self.x0 - d, self.y0 - d, self.x1 + d, self.y1 + d)

    def intersects(self, other):
        parts = getattr(other, "parts", None)
        if parts:
            return any(self.intersects(p) for p in parts)
        return (self.x0 < other.x1 and other.x0 < self.x1
                and self.y0 < other.y1 and other.y0 < self.y1)

    def inside(self, other, tol=0.5):
        return (self.x0 >= other.x0 - tol and self.y0 >= other.y0 - tol
                and self.x1 <= other.x1 + tol and self.y1 <= other.y1 + tol)

    def union(self, other):
        return Rect(min(self.x0, other.x0), min(self.y0, other.y0),
                    max(self.x1, other.x1), max(self.y1, other.y1))

    def distance(self, other):
        dx = max(other.x0 - self.x1, self.x0 - other.x1, 0)
        dy = max(other.y0 - self.y1, self.y0 - other.y1, 0)
        return max(dx, dy) if (dx == 0 or dy == 0) else math.hypot(dx, dy)


class _UnionRect(Rect):
    """Unión de dos rectángulos (forma en T) que se comporta como Rect para
    intersecciones; la caja envolvente se usa para todo lo demás."""

    def __init__(self, a, b):
        env = a.union(b)
        super().__init__(env.x0, env.y0, env.x1, env.y1)
        self.parts = (a, b)

    def inflate(self, d):
        return _UnionRect(self.parts[0].inflate(d), self.parts[1].inflate(d))

    def intersects(self, other):
        others = getattr(other, "parts", (other,))
        return any(Rect.intersects(p, o) for p in self.parts for o in others)


def _to_frame(rect, orient, W, H):
    """Página -> marco de lectura (u a lo largo del texto, v hacia la línea siguiente)."""
    if orient == "I":
        return Rect(W - rect.x1, H - rect.y1, W - rect.x0, H - rect.y0)
    if orient == "B":
        return Rect(H - rect.y1, rect.x0, H - rect.y0, rect.x1)
    if orient == "R":
        return Rect(rect.y0, W - rect.x1, rect.y1, W - rect.x0)
    return Rect(rect.x0, rect.y0, rect.x1, rect.y1)


def _from_frame(rect, orient, W, H):
    if orient == "I":
        return Rect(W - rect.x1, H - rect.y1, W - rect.x0, H - rect.y0)
    if orient == "B":
        return Rect(rect.y0, H - rect.x1, rect.y1, H - rect.x0)
    if orient == "R":
        return Rect(W - rect.y1, rect.x0, W - rect.y0, rect.x1)
    return Rect(rect.x0, rect.y0, rect.x1, rect.y1)
