# -*- coding: utf-8 -*-
"""
pal_parser.py
=============
Lector de paletas de color de radar en formato .pal (estilo WXTools.org / GR2Analyst).

Formatos soportados:

1) Formato simple (WXTools "Color:"):
       Color: <valor> <R> <G> <B>
   Cada linea define un punto (stop) de la paleta. Los valores intermedios
   se interpolan linealmente entre stops consecutivos (colormap continuo).

2) Formato "Color4:" (GR2Analyst / gradiente explicito, 2 colores por linea):
       Color4: <v1> <r1> <g1> <b1> <a1>  <v2> <r2> <g2> <b2> <a2>
   Define un segmento con gradiente propio entre v1 y v2. Se arman todos
   los segmentos y se concatenan.

3) Metadatos opcionales (se ignoran para el color pero quedan disponibles):
       Product: <nombre>
       Units: <unidad>
       Min: <valor>
       Max: <valor>
       Step: <valor>

Lineas que empiezan con ';' o '#' son comentarios.

Uso:
    from radarplot.pal_parser import load_pal
    cmap, norm, meta = load_pal("palettes/VRAD_default.pal")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.colors import LinearSegmentedColormap, Normalize


@dataclass
class PalMeta:
    product: str | None = None
    units: str | None = None
    vmin: float | None = None
    vmax: float | None = None
    step: float | None = None
    raw_stops: list = field(default_factory=list)  # [(value, (r,g,b)), ...]


_COLOR_RE = re.compile(
    r"^Color:\s*([-\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)", re.IGNORECASE
)
_COLOR4_RE = re.compile(
    r"^Color4:\s*"
    r"([-\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+"
    r"([-\d.]+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
    re.IGNORECASE,
)
_META_RE = re.compile(r"^(Product|Units|Min|Max|Step):\s*(.+)$", re.IGNORECASE)


def _parse_lines(text: str) -> PalMeta:
    meta = PalMeta()
    stops: list[tuple[float, tuple[int, int, int]]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue

        m4 = _COLOR4_RE.match(line)
        if m4:
            v1, r1, g1, b1, _a1, v2, r2, g2, b2, _a2 = m4.groups()
            stops.append((float(v1), (int(r1), int(g1), int(b1))))
            stops.append((float(v2), (int(r2), int(g2), int(b2))))
            continue

        m1 = _COLOR_RE.match(line)
        if m1:
            v, r, g, b = m1.groups()
            stops.append((float(v), (int(r), int(g), int(b))))
            continue

        mm = _META_RE.match(line)
        if mm:
            key, val = mm.groups()
            key = key.lower()
            val = val.strip()
            if key == "product":
                meta.product = val
            elif key == "units":
                meta.units = val
            elif key == "min":
                meta.vmin = float(val)
            elif key == "max":
                meta.vmax = float(val)
            elif key == "step":
                meta.step = float(val)
            continue
        # Lineas no reconocidas se ignoran silenciosamente (robustez ante
        # variantes de formato .pal de distintas herramientas).

    stops.sort(key=lambda s: s[0])
    meta.raw_stops = stops
    if meta.vmin is None and stops:
        meta.vmin = stops[0][0]
    if meta.vmax is None and stops:
        meta.vmax = stops[-1][0]
    return meta


def load_pal(path: str | Path, n_colors: int = 256):
    """
    Carga un archivo .pal y devuelve (cmap, norm, meta).

    cmap : matplotlib.colors.LinearSegmentedColormap
    norm : matplotlib.colors.Normalize (vmin/vmax segun el archivo)
    meta : PalMeta con product/units/vmin/vmax/step y los stops crudos
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    meta = _parse_lines(text)

    if not meta.raw_stops:
        raise ValueError(f"No se encontraron stops de color validos en {path}")

    vmin, vmax = meta.vmin, meta.vmax
    span = vmax - vmin if vmax > vmin else 1.0

    positions = [(v - vmin) / span for v, _ in meta.raw_stops]
    colors = [(r / 255, g / 255, b / 255) for _, (r, g, b) in meta.raw_stops]

    # Evitar posiciones duplicadas exactas (matplotlib exige estrictamente creciente)
    cleaned_pos, cleaned_col = [], []
    last = -1.0
    for p, c in zip(positions, colors):
        p = min(max(p, 0.0), 1.0)
        if p <= last:
            p = min(last + 1e-6, 1.0)
        cleaned_pos.append(p)
        cleaned_col.append(c)
        last = p
    cleaned_pos[0] = 0.0
    cleaned_pos[-1] = 1.0

    cmap = LinearSegmentedColormap.from_list(
        path.stem, list(zip(cleaned_pos, cleaned_col)), N=n_colors
    )
    # Sin color para NaN / fuera de rango -> transparente (se maneja en el plot)
    cmap.set_bad(alpha=0.0)

    norm = Normalize(vmin=vmin, vmax=vmax, clip=False)
    return cmap, norm, meta


def load_pal_discrete(path: str | Path):
    """
    Variante 'a bandas' (no interpolada): cada stop define el color de un
    escalon hasta el siguiente valor. Util quando la paleta original del
    radar es escalonada (como la mayoria de las paletas de reflectividad
    y velocidad tipo NWS/SINARAME) en vez de un degrade continuo.
    """
    from matplotlib.colors import BoundaryNorm, ListedColormap

    path = Path(path)
    meta = _parse_lines(path.read_text(encoding="utf-8"))
    if not meta.raw_stops:
        raise ValueError(f"No se encontraron stops de color validos en {path}")

    values = [v for v, _ in meta.raw_stops]
    colors = [(r / 255, g / 255, b / 255) for _, (r, g, b) in meta.raw_stops]

    cmap = ListedColormap(colors, name=path.stem)
    cmap.set_bad(alpha=0.0)
    norm = BoundaryNorm(values + [values[-1] + (meta.step or 1.0)], cmap.N)
    return cmap, norm, meta
