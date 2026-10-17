"""Rutas del programa y de sus recursos (código fuente o .exe de PyInstaller)."""

import os
import sys


def app_dir():
    """Carpeta del programa: junto al .exe en la versión compilada, o la del código."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts):
    """Ruta de un recurso (icono, fondo…). Primero se busca junto al programa, para
    poder reemplazarlo en la versión portable; si no está, dentro del .exe."""
    candidates = [os.path.join(app_dir(), *parts)]
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        candidates.append(os.path.join(bundled, *parts))
    return next((path for path in candidates if os.path.exists(path)), candidates[0])
