# -*- coding: utf-8 -*-
"""
title.py
========
Arma el titulo del plot con el formato pedido:

    {Localidad}-{Organismo} {Producto} [{unidad}] {fecha} {horaART} ART {horaUTC} UTC

Ejemplo:
    "Parana-SINARAME / INTA PPI0.5 [m/s] 03.05.2018 19:14:32 ART 22:14:32 UTC"
"""
from __future__ import annotations

import datetime as _dt

ART_OFFSET = _dt.timedelta(hours=-3)


def utc_to_art(dt_utc: _dt.datetime) -> _dt.datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=_dt.timezone.utc)
    return dt_utc.astimezone(_dt.timezone(ART_OFFSET))


_PRODUCT_UNITS = {
    "DBZH": "dBZ", "DBZHO": "dBZ",
    "COLMAX": "dBZ", "COLMAXO": "dBZ",
    "VRAD": "m/s", "VRADO": "m/s",
    "WRAD": "m/s", "WRADO": "m/s",
}

_PRODUCT_NO_ELEVATION = {"COLMAX", "COLMAXO"}  # productos compuestos (sin PPI)


def product_abbrev_and_units(product_key: str, elevation_angle: float | None = None) -> tuple[str, str]:
    """
    Traduce un product_key real de la API OHMC (ej "DBZHo", "VRADo",
    "COLMAX") a una abreviatura de titulo + unidad, ej:
        ("DBZHo", 0.5)  -> ("PPI0.5", "dBZ")
        ("COLMAX", None) -> ("COLMAX", "dBZ")
    """
    key_upper = product_key.upper()
    units = _PRODUCT_UNITS.get(key_upper, "")
    if key_upper in _PRODUCT_NO_ELEVATION or elevation_angle is None:
        return product_key, units
    return f"PPI{elevation_angle:g}", units


def build_title(localidad: str, organismo: str, producto_abrev: str,
                 unidad: str, dt_utc: _dt.datetime, vcp: str = "") -> str:
    """
    localidad       : ej "Parana"
    organismo       : ej "SINARAME / INTA"
    producto_abrev  : ej "PPI0.5"
    unidad          : ej "m/s" o "dBZ"
    dt_utc          : datetime timezone-aware (o naive asumido UTC)
    vcp             : opcional, ej "VCP1000.02"
    """
    dt_art = utc_to_art(dt_utc)

    fecha = dt_utc.strftime("%d.%m.%Y")
    hora_art = dt_art.strftime("%H:%M:%S")
    hora_utc = dt_utc.strftime("%H:%M:%S")

    titulo = (
        f"{localidad}-{organismo} {producto_abrev} [{unidad}] "
        f"{fecha} {hora_art} ART {hora_utc} UTC"
    )
    if vcp:
        titulo += f" {vcp}"
    return titulo
