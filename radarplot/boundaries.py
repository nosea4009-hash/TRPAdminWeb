# -*- coding: utf-8 -*-
"""
boundaries.py
=============
Carga y dibuja los limites provinciales (ar.json) y departamentales
(departamentos.geojson) sobre un GeoAxes/Axes de matplotlib.

Ambos archivos son GeoJSON FeatureCollection standard:
  - ar.json              -> 24 features (23 provincias + CABA), properties: id, name
  - departamentos.geojson -> 529 features, properties: id, nombre, provincia.{id,nombre}

No se requiere geopandas: se recorre el geojson "a mano" para no agregar
una dependencia pesada. Soporta geometrias Polygon y MultiPolygon.
"""
from __future__ import annotations

import json
from pathlib import Path

from matplotlib.collections import LineCollection


def _polygon_rings(geometry: dict):
    """Devuelve una lista de anillos [(lon,lat), ...] para Polygon o MultiPolygon."""
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    rings = []
    if gtype == "Polygon":
        for ring in coords:
            rings.append(ring)
    elif gtype == "MultiPolygon":
        for poly in coords:
            for ring in poly:
                rings.append(ring)
    return rings


def load_geojson(path: str | Path) -> dict:
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _segments_from_features(features, bbox=None):
    """Convierte features geojson en segmentos de linea (para LineCollection),
    recortando (bbox filter simple) por performance si se indica bbox=(lon0,lon1,lat0,lat1).
    """
    segments = []
    for feat in features:
        geom = feat.get("geometry")
        if not geom:
            continue
        for ring in _polygon_rings(geom):
            if bbox is not None:
                lon0, lon1, lat0, lat1 = bbox
                xs = [p[0] for p in ring]
                ys = [p[1] for p in ring]
                if max(xs) < lon0 or min(xs) > lon1 or max(ys) < lat0 or min(ys) > lat1:
                    continue
            for i in range(len(ring) - 1):
                p0 = ring[i]
                p1 = ring[i + 1]
                segments.append([(p0[0], p0[1]), (p1[0], p1[1])])
    return segments


def plot_provinces(ax, geojson_path, bbox=None, color="#8c8c8c", linewidth=0.9,
                    zorder=5, alpha=1.0):
    """Dibuja los limites provinciales (ar.json) en negro-grisaceo fino."""
    data = load_geojson(geojson_path)
    segs = _segments_from_features(data["features"], bbox=bbox)
    lc = LineCollection(segs, colors=color, linewidths=linewidth,
                         zorder=zorder, alpha=alpha, capstyle="round")
    ax.add_collection(lc)
    return lc


def plot_departments(ax, geojson_path, bbox=None, color="#5f5f5f", linewidth=0.4,
                      zorder=4, alpha=0.9, provincia_filter=None):
    """
    Dibuja los limites departamentales (departamentos.geojson).

    provincia_filter: nombre (o lista de nombres) de provincia para limitar
    el dibujo (mejora performance en radares regionales). Ej: "Entre Ríos"
    o ["Entre Ríos", "Santa Fe", "Corrientes"].
    """
    data = load_geojson(geojson_path)
    feats = data["features"]

    if provincia_filter is not None:
        if isinstance(provincia_filter, str):
            provincia_filter = [provincia_filter]
        wanted = {_normalize_province_name(p) for p in provincia_filter}
        feats = [
            f for f in feats
            if _normalize_province_name(
                f["properties"].get("provincia", {}).get("nombre", "")
            ) in wanted
        ]

    segs = _segments_from_features(feats, bbox=bbox)
    lc = LineCollection(segs, colors=color, linewidths=linewidth,
                         zorder=zorder, alpha=alpha, capstyle="round")
    ax.add_collection(lc)
    return lc


# Algunas provincias tienen nombres ligeramente distintos entre ar.json
# (limites provinciales) y departamentos.geojson (que trae su propio
# provincia.nombre por departamento). Se normalizan ambos lados a una
# forma canonica antes de comparar, para que el filtro por provincia
# funcione igual sin importar de que archivo vino el nombre.
_PROVINCE_ALIASES = {
    "ciudad de buenos aires": "caba",
    "ciudad autónoma de buenos aires": "caba",
    "ciudad autonoma de buenos aires": "caba",
    "tierra del fuego": "tierra del fuego",
    "tierra del fuego, antártida e islas del atlántico sur": "tierra del fuego",
    "tierra del fuego, antartida e islas del atlantico sur": "tierra del fuego",
}


def _normalize_province_name(name: str) -> str:
    key = name.strip().lower()
    return _PROVINCE_ALIASES.get(key, key)


def _get_province_name(properties: dict) -> str | None:
    """
    Extrae el nombre de provincia de una feature, soportando tanto el
    esquema de ar.json (propiedad "name" plana) como el de
    departamentos.geojson (propiedad anidada "provincia.nombre").
    """
    if "provincia" in properties:  # esquema departamentos.geojson
        return properties.get("provincia", {}).get("nombre")
    return properties.get("name") or properties.get("nombre")  # esquema ar.json


def provinces_near(geojson_path, center_lon, center_lat, radius_km=240.0):
    """
    Devuelve la lista de nombres de provincia cuyo bbox intersecta el
    circulo de cobertura del radar (uso: pasar a provincia_filter en
    plot_departments para no cargar el pais entero).
    """
    data = load_geojson(geojson_path)
    deg_pad = radius_km / 111.0  # aprox grados por km
    lon0, lon1 = center_lon - deg_pad, center_lon + deg_pad
    lat0, lat1 = center_lat - deg_pad, center_lat + deg_pad

    names = set()
    for feat in data["features"]:
        geom = feat.get("geometry")
        if not geom:
            continue
        for ring in _polygon_rings(geom):
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if max(xs) < lon0 or min(xs) > lon1 or max(ys) < lat0 or min(ys) > lat1:
                continue
            prov = _get_province_name(feat["properties"])
            if prov:
                names.add(prov)
            break
    return sorted(names)
