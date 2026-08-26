# -*- coding: utf-8 -*-
"""
metpy_palette.py
================
Paletas de radar "con nombre" (no archivo .pal), tomadas de las
colortables que trae MetPy (metpy.plots.ctables). Pensado para paletas
estandar/reconocidas (NWS, etc.) que no tiene sentido reinventar a mano
en un .pal, a diferencia de las paletas custom (ver pal_parser.py).

Uso:
    from radarplot.metpy_palette import load_metpy_colortable
    cmap, norm = load_metpy_colortable("NWSReflectivityExpanded", -20.0, 5.0)
"""
from __future__ import annotations


def load_metpy_colortable(table_name: str, start: float, step: float):
    """
    Devuelve (cmap, norm) de una colortable de MetPy, lista para usar en
    pcolormesh igual que las paletas .pal propias.

    table_name: nombre de la colortable de MetPy (ver
        metpy.plots.ctables.registry para la lista completa; algunas
        utiles para radar: "NWSReflectivityExpanded", "NWSReflectivity",
        "NWSStormClearReflectivity", "NWSVelocity", "NWS8bitVel",
        "NWSSpectrumWidth").
    start: valor fisico del primer escalon (ej -20.0 dBZ).
    step: ancho de cada escalon (ej 5.0 dBZ). El numero de escalones lo
        define la propia tabla de MetPy, no se elige aca.
    """
    try:
        from metpy.plots import ctables
    except ImportError as exc:
        raise ImportError(
            "Falta instalar 'metpy' para usar paletas con nombre "
            "(--palette). Instalalo con: pip install metpy "
            "(o agregalo a tu environment.yml / requirements.txt)."
        ) from exc

    norm, cmap = ctables.registry.get_with_steps(table_name, start, step)
    # copia para no mutar el colormap compartido del registro de MetPy
    # al llamar set_bad (celdas NaN = sin dato -> transparentes, igual
    # que con las paletas .pal propias)
    cmap = cmap.copy()
    cmap.set_bad(alpha=0.0)
    return cmap, norm
