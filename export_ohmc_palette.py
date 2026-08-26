# -*- coding: utf-8 -*-
"""
export_ohmc_palette.py
=======================
Exporta un colormap OFICIAL de OHMC (el que ellos mismos disenaron y
calibraron para sus datos) como archivo .pal, listo para usar con
--pal. Mas confiable que armar una paleta a mano, porque ya viene
calibrada al rango real de cada producto.

Uso:
    python export_ohmc_palette.py --product DBZH --out palettes/dBZ_ohmc.pal
    python export_ohmc_palette.py --product DBZH --colormap grc_th --out palettes/dBZ_ohmc.pal
    python export_ohmc_palette.py --product VRADo --out palettes/VRAD_ohmc.pal

Colormaps disponibles tipicamente: grc_th, grc_th2, grc_rain, grc_g,
grayscale (para ver los disponibles de un producto puntual, mira el
campo "available_colormaps" que devuelve /api/v1/colormap/info/{product}).

Despues de generarlo, si queres que sea la paleta por defecto para ese
tipo de dato, actualiza PAL_FILES_BY_UNIT en config.py para que apunte
al archivo generado.
"""
import argparse

from radarplot.ohmc_client import colormap_info_to_pal, get_colormap_info
from radarplot.title import _PRODUCT_UNITS

parser = argparse.ArgumentParser()
parser.add_argument("--product", required=True, help="product_key, ej DBZH, VRADo")
parser.add_argument("--colormap", default=None,
                     help="Nombre del colormap oficial (grc_th, grc_th2, "
                          "grc_rain, grc_g). Si no se pasa, usa el default "
                          "del backend para ese producto.")
parser.add_argument("--out", required=True, help="Ruta del .pal de salida")
args = parser.parse_args()

info = get_colormap_info(args.product, colormap=args.colormap)
print(f"Colormap oficial de {args.product}: '{info['colormap']}' "
      f"(rango {info['vmin']} a {info['vmax']}, {len(info['colors'])} colores)")
print(f"Colormaps disponibles para este producto: {info.get('available_colormaps')}")

units = _PRODUCT_UNITS.get(args.product.upper(), "")
colormap_info_to_pal(args.product, args.colormap, args.out, units=units)
print(f"\nListo -> {args.out}")
print(f"Probalo con: python plot_radar.py --live --product {args.product} --pal {args.out}")
