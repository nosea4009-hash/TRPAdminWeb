# -*- coding: utf-8 -*-
"""
diagnose.py
===========
Script standalone de verificacion para la decodificacion de imagenes
grayscale de la API de OHMC. Se corre directo, sin pegar nada en una
consola interactiva:

    python diagnose.py
    python diagnose.py --radar RMA11 --product DBZHo

    # apuntar a un frame historico puntual (ej el de una supercelda
    # que se veia rara), igual que en plot_radar.py:
    python diagnose.py --radar RMA2 --product DBZH --at 2026-07-31T22:10:00Z

Baja el frame pedido (el mas reciente, o el mas cercano a --at/--days-ago),
pide su imagen con colormap=grayscale, y prueba las 4 combinaciones
posibles de decodificacion (rango fijo del producto vs rango propio del
frame, cada uno normal e invertido), comparando contra data_min/data_max
y mostrando percentiles para juzgar si la distribucion tiene sentido
fisico. Con eso deberia quedar claro cual combinacion es la correcta -
la que uses en config.py (GRAYSCALE_INVERTED) para el resto del proyecto.
"""
import argparse
import datetime as dt

import config as cfg
from radarplot.ohmc_client import (
    get_latest_cog, find_cog_nearest, verify_grayscale_decoding,
)

parser = argparse.ArgumentParser()
parser.add_argument("--radar", default=cfg.RADAR_CODE)
parser.add_argument("--product", default=cfg.PRODUCT_KEY)
parser.add_argument("--at", default=None,
                     help="Fecha/hora UTC ISO8601 puntual, ej "
                          "2026-07-31T22:10:00Z. Si no se pasa, usa el "
                          "frame mas reciente.")
parser.add_argument("--days-ago", type=float, default=None,
                     help="Atajo: 'ahora menos N dias' en vez de --at")
parser.add_argument("--search-window", type=float, default=15)
args = parser.parse_args()

target_utc = None
if args.at:
    target_utc = dt.datetime.fromisoformat(args.at.replace("Z", "+00:00"))
elif args.days_ago is not None:
    target_utc = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days_ago)

if target_utc:
    print(f"Buscando frame de radar={args.radar} product={args.product} "
          f"mas cercano a {target_utc.isoformat()} ...\n")
    cog = find_cog_nearest(args.radar, args.product, target_utc,
                            search_window_days=args.search_window)
else:
    print(f"Buscando ultimo frame de radar={args.radar} product={args.product} ...\n")
    cog = get_latest_cog(args.radar, args.product, vol_nr=cfg.VOL_NR, strategy=cfg.STRATEGY)

print(f"COG encontrado: id={cog.id} observation_time={cog.observation_time}")
print(f"bbox={cog.bbox}\n")

verify_grayscale_decoding(cog)
