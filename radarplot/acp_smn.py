# -*- coding: utf-8 -*-
"""
acp_smn.py
==========
Descarga y parsea los Avisos a Muy Corto Plazo (ACP) del SMN, publicados
como feed CAP (Common Alerting Protocol) en:

    https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml

El feed es un RSS donde cada <item> apunta (via <link> o <guid>) a un
documento CAP individual (XML) que contiene, entre otras cosas, un tag
<area><polygon> con la lista de puntos "lat,lon lat,lon ...".

Este modulo:
  1. Descarga el RSS "indice".
  2. Descarga cada CAP individual referenciado.
  3. Extrae el poligono (lista de (lon,lat)) de cada aviso vigente.

Uso:
    from radarplot.acp_smn import fetch_acp_polygons
    polys = fetch_acp_polygons()
    # polys -> lista de dicts: {"polygon": [(lon,lat),...], "titulo": str,
    #                           "descripcion": str, "expires": datetime, ...}
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

ACP_RSS_URL = "https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml"

_CAP_NS = {"cap": "urn:oasis:names:tc:emergency:cap:1.2"}
_RSS_ITEM_TAGS = ("link", "guid")


@dataclass
class AcpAviso:
    titulo: str = ""
    descripcion: str = ""
    sender: str = ""
    effective: _dt.datetime | None = None
    expires: _dt.datetime | None = None
    polygon: list = field(default_factory=list)  # [(lon, lat), ...]


def _parse_cap_polygon(polygon_text: str) -> list[tuple[float, float]]:
    """CAP usa 'lat,lon lat,lon ...' -> devolvemos (lon,lat) para matplotlib/cartopy."""
    pts = []
    for pair in polygon_text.strip().split():
        lat_s, lon_s = pair.split(",")
        pts.append((float(lon_s), float(lat_s)))
    return pts


def _parse_cap_datetime(s: str | None) -> _dt.datetime | None:
    if not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _fetch_cap_item(url: str, session: requests.Session, timeout: int = 15) -> list[AcpAviso]:
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    avisos = []
    infos = root.findall("cap:info", _CAP_NS)
    if not infos:
        return avisos

    for info in infos:
        headline = info.findtext("cap:headline", default="", namespaces=_CAP_NS)
        description = info.findtext("cap:description", default="", namespaces=_CAP_NS)
        sender = root.findtext("cap:sender", default="", namespaces=_CAP_NS)
        effective = _parse_cap_datetime(info.findtext("cap:effective", namespaces=_CAP_NS))
        expires = _parse_cap_datetime(info.findtext("cap:expires", namespaces=_CAP_NS))

        for area in info.findall("cap:area", _CAP_NS):
            for poly_el in area.findall("cap:polygon", _CAP_NS):
                if not poly_el.text:
                    continue
                avisos.append(
                    AcpAviso(
                        titulo=headline,
                        descripcion=description,
                        sender=sender,
                        effective=effective,
                        expires=expires,
                        polygon=_parse_cap_polygon(poly_el.text),
                    )
                )
    return avisos


def fetch_acp_polygons(rss_url: str = ACP_RSS_URL, timeout: int = 15,
                        only_vigentes: bool = True) -> list[AcpAviso]:
    """
    Descarga el indice RSS de ACP y todos los CAP individuales referenciados,
    devolviendo la lista de poligonos vigentes.

    only_vigentes: si True, descarta avisos cuyo campo <expires> ya paso
    (usa la hora UTC actual). Si el CAP no trae expires, se conserva.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": "radar-ohmc-plot/1.0"})

    resp = session.get(rss_url, timeout=timeout)
    resp.raise_for_status()
    rss_root = ET.fromstring(resp.content)

    item_urls = []
    for item in rss_root.iter("item"):
        for tag in _RSS_ITEM_TAGS:
            el = item.find(tag)
            if el is not None and el.text:
                item_urls.append(el.text.strip())
                break

    all_avisos: list[AcpAviso] = []
    for url in item_urls:
        try:
            all_avisos.extend(_fetch_cap_item(url, session, timeout=timeout))
        except (requests.RequestException, ET.ParseError):
            # Un CAP individual caido no debe tirar abajo todo el plot.
            continue

    if only_vigentes:
        now = _dt.datetime.now(_dt.timezone.utc)
        filtered = []
        for a in all_avisos:
            if a.expires is None:
                filtered.append(a)
                continue
            exp = a.expires
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=_dt.timezone.utc)
            if exp >= now:
                filtered.append(a)
        all_avisos = filtered

    return all_avisos
