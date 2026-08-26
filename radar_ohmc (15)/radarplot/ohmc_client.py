# -*- coding: utf-8 -*-
"""
ohmc_client.py
==============
Cliente para la API real del visor de radar del OHMC (webmet.ohmc.ar).

IMPORTANTE - como se obtienen los datos (version final, confirmada):
-------------------------------------------------------------------------
El OHMC NO expone descarga directa de GeoTIFF/valores crudos. Lo que
expone es un endpoint que renderiza, del lado del servidor, una imagen
PNG a partir del dato para un "frame" puntual:

    GET https://webmet.ohmc.ar/api/v1/frames/{id}/image.png?colormap=X

`id` es el mismo "id" que trae cada registro de /api/v1/cogs (y
/api/v1/cogs/latest). `colormap` puede ser cualquiera de los oficiales
del OHMC (grc_th, grc_th2, grc_rain, grc_g) O, la clave para nosotros,
**"grayscale"**.

Cuando pedis colormap=grayscale, el valor de gris de cada pixel (0-255)
es una codificacion LINEAL del valor fisico real entre el rango oficial
del producto (`cog_vmin`..`cog_vmax`, el mismo rango que devuelve
/api/v1/colormap/info/{product_key}). Es decir, podemos RECONSTRUIR el
valor fisico real de cada pixel:

    valor = cog_vmin + (cog_vmax - cog_vmin) * (gris / 255)

...y a partir de ahi aplicarle cualquier paleta .pal propia, exactamente
igual que si hubieramos descargado un GeoTIFF raw_float. Sin rasterio,
sin GDAL, sin dolores de cabeza de instalacion: solo Pillow.

Endpoints usados:
  GET /api/v1/cogs?radar_code=...&product_key=...        -> listar frames
  GET /api/v1/cogs/latest?radar_code=...&product_key=...  -> el mas reciente
  GET /api/v1/colormap/info/{product_key}?colormap=...     -> colores oficiales
  GET /api/v1/frames/{id}/image.png?colormap=grayscale     -> imagen para
                                                               decodificar
  GET /api/v1/frames/{id}/image.png?colormap=grc_th (etc)  -> imagen YA
                                                               coloreada
                                                               (vista rapida,
                                                               no sirve para
                                                               paleta propia)

Cada registro "cog" (ver `CogMeta`) trae ademas `bbox` (georreferenciacion),
`data_min`/`data_max` (rango real de ESE frame puntual, mas angosto que
cog_vmin/cog_vmax), y `radar_coverage_m` (alcance en metros).
"""
from __future__ import annotations

import datetime as _dt
import io
from dataclasses import dataclass

import numpy as np
import requests
from PIL import Image

API_BASE = "https://webmet.ohmc.ar/api/v1"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "image/png,*/*",
    "Referer": "https://webmet.ohmc.ar/",
}


@dataclass
class CogMeta:
    id: int
    radar_code: str
    product_key: str
    product_id: int
    observation_time: str
    elevation_angle: float
    file_path: str
    file_name: str
    data_min: float
    data_max: float
    bbox: dict
    tile_url: str
    cog_data_type: str
    cog_cmap: str
    cog_vmin: float
    cog_vmax: float
    strategy: str
    vol_nr: str
    radar_coverage_m: float

    @classmethod
    def from_json(cls, j: dict) -> "CogMeta":
        return cls(**{k: j[k] for k in cls.__dataclass_fields__ if k in j})


@dataclass
class RadarGrid:
    values: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    site_lon: float
    site_lat: float
    timestamp_utc: str
    product: str
    elevation: str
    units: str
    vcp: str = ""
    radar_code: str = ""


# ------------------------------------------------------------------
# Listado / busqueda de COGs
# ------------------------------------------------------------------
def list_cogs(radar_code: str | None = None, product_key: str | None = None,
              page: int = 1, page_size: int = 50, timeout: int = 20) -> list[CogMeta]:
    params = {"page": page, "page_size": page_size}
    if radar_code:
        params["radar_code"] = radar_code
    if product_key:
        params["product_key"] = product_key
    resp = requests.get(f"{API_BASE}/cogs", params=params,
                         headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    j = resp.json()
    return [CogMeta.from_json(c) for c in j["cogs"]]


def get_latest_cog(radar_code: str, product_key: str,
                    vol_nr=None, strategy=None, timeout: int = 20) -> CogMeta:
    """
    Trae el frame mas reciente disponible para un radar+producto.
    vol_nr / strategy aceptan un valor o una lista (se repiten como
    parametros multiples en el query string, igual que en la URL que
    encontraste: vol_nr=01&vol_nr=02&vol_nr=03).
    """
    params = [("radar_code", radar_code), ("product_key", product_key)]
    for name, val in (("vol_nr", vol_nr), ("strategy", strategy)):
        if val is None:
            continue
        vals = [val] if isinstance(val, str) else list(val)
        params.extend((name, v) for v in vals)

    resp = requests.get(f"{API_BASE}/cogs/latest", params=params,
                         headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return CogMeta.from_json(resp.json())


# ------------------------------------------------------------------
# Busqueda historica (frames mas viejos, hasta ~10-15 dias atras)
# ------------------------------------------------------------------
# El endpoint /api/v1/cogs no confirmamos que tenga filtro de fecha
# propio (date_from/date_to), asi que esto pagina sobre /cogs y filtra
# del lado del cliente por observation_time. Si en algun momento
# encontras un parametro de fecha nativo en la API, esto se puede
# simplificar mucho (una sola request en vez de paginar).


def _parse_obs_time(cog: CogMeta) -> _dt.datetime:
    return _dt.datetime.fromisoformat(cog.observation_time.replace("Z", "+00:00"))


def list_cogs_in_range(radar_code: str, product_key: str,
                        since_utc: _dt.datetime, until_utc: _dt.datetime | None = None,
                        page_size: int = 200, max_pages: int = 100,
                        timeout: int = 20) -> list[CogMeta]:
    """
    Devuelve todos los frames de radar_code/product_key con
    since_utc <= observation_time <= until_utc (por defecto, hasta ahora),
    ordenados de mas viejo a mas nuevo.

    Pagina sobre /api/v1/cogs (sin asumir el orden en que el backend
    devuelve los resultados) hasta cubrir el rango pedido o llegar a
    max_pages. Para un rango de ~10-15 dias con productos que se
    generan cada 5-10 min, esto puede ser bastante paginas: subi
    page_size si hace falta.
    """
    if since_utc.tzinfo is None:
        since_utc = since_utc.replace(tzinfo=_dt.timezone.utc)
    until_utc = until_utc or _dt.datetime.now(_dt.timezone.utc)
    if until_utc.tzinfo is None:
        until_utc = until_utc.replace(tzinfo=_dt.timezone.utc)

    collected: dict[int, CogMeta] = {}
    page = 1
    while page <= max_pages:
        batch = list_cogs(radar_code=radar_code, product_key=product_key,
                           page=page, page_size=page_size, timeout=timeout)
        if not batch:
            break
        for c in batch:
            collected[c.id] = c

        times = [_parse_obs_time(c) for c in batch]
        oldest_in_batch = min(times)
        newest_in_batch = max(times)

        # Si TODO lo que trajo esta pagina ya es mas viejo que el rango
        # pedido, asumimos que no hace falta seguir pidiendo paginas mas
        # "profundas" (esto funciona tanto si el backend ordena
        # descendente como si no, porque igual paramos apenas dejamos de
        # ver frames dentro o mas nuevos que el rango).
        if newest_in_batch < since_utc and oldest_in_batch < since_utc:
            break
        page += 1

    filtered = [c for c in collected.values()
                if since_utc <= _parse_obs_time(c) <= until_utc]
    filtered.sort(key=_parse_obs_time)
    return filtered


def find_cog_nearest(radar_code: str, product_key: str, target_utc: _dt.datetime,
                      search_window_days: float = 15, page_size: int = 200,
                      max_pages: int = 100, timeout: int = 20) -> CogMeta:
    """
    Busca el frame disponible mas cercano a una fecha/hora UTC puntual,
    buscando dentro de +-search_window_days alrededor de target_utc
    (por defecto hasta 15 dias para cada lado).

    Uso:
        from datetime import datetime, timezone, timedelta
        target = datetime.now(timezone.utc) - timedelta(days=5)
        cog = find_cog_nearest("RMA1", "DBZH", target)
    """
    if target_utc.tzinfo is None:
        target_utc = target_utc.replace(tzinfo=_dt.timezone.utc)
    since = target_utc - _dt.timedelta(days=search_window_days)
    until = target_utc + _dt.timedelta(days=search_window_days)

    candidates = list_cogs_in_range(radar_code, product_key, since, until,
                                     page_size=page_size, max_pages=max_pages,
                                     timeout=timeout)
    if not candidates:
        raise RuntimeError(
            f"No se encontraron frames de {radar_code}/{product_key} entre "
            f"{since.isoformat()} y {until.isoformat()}. Probá agrandar "
            "search_window_days, o confirmá que ese radar/producto tenga "
            "historico disponible para esa fecha."
        )
    return min(candidates, key=lambda c: abs(_parse_obs_time(c) - target_utc))


def get_colormap_info(product_key: str, colormap: str | None = None,
                       timeout: int = 20) -> dict:
    """
    Devuelve {product_key, colormap, vmin, vmax, colors:[...256 hex...],
    ticks:[{value,color},...], available_colormaps:[...]}.
    """
    params = {"colormap": colormap} if colormap else {}
    resp = requests.get(f"{API_BASE}/colormap/info/{product_key}",
                         params=params, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def colormap_info_to_pal(product_key: str, colormap: str | None,
                          out_path: str, units: str = "") -> str:
    """
    Convierte el colormap oficial del OHMC (via /colormap/info) a un
    archivo .pal compatible con radarplot.pal_parser, para usarlo como
    punto de partida y despues editarlo a gusto.
    """
    info = get_colormap_info(product_key, colormap=colormap)
    colors = info["colors"]
    vmin, vmax = info["vmin"], info["vmax"]
    n = len(colors)

    lines = [
        f"; Paleta exportada desde OHMC ({product_key}, colormap={info['colormap']})",
        f"Product: {product_key}",
        f"Units: {units}",
        f"Min: {vmin}",
        f"Max: {vmax}",
    ]
    for i, hexcolor in enumerate(colors):
        val = vmin + (vmax - vmin) * i / (n - 1)
        r = int(hexcolor[1:3], 16)
        g = int(hexcolor[3:5], 16)
        b = int(hexcolor[5:7], 16)
        lines.append(f"Color: {val:.3f} {r} {g} {b}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


# ------------------------------------------------------------------
# Descarga + decodificacion de la imagen grayscale -> valores fisicos
# ------------------------------------------------------------------
def fetch_frame_image(cog_id: int, colormap: str = "grayscale",
                       timeout: int = 30) -> Image.Image:
    """Baja /api/v1/frames/{id}/image.png?colormap=... y la abre con PIL."""
    url = f"{API_BASE}/frames/{cog_id}/image.png"
    resp = requests.get(url, params={"colormap": colormap},
                         headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def decode_grayscale_image(im: Image.Image, vmin: float, vmax: float,
                            invert: bool = False) -> np.ndarray:
    """
    Convierte una imagen PIL (modo L, LA, RGB o RGBA) obtenida con
    colormap=grayscale en un array 2D de valores FISICOS reales.

    - Si la imagen tiene canal alpha, alpha=0 se interpreta como "sin dato"
      (NaN). Si no tiene alpha, no se aplica mascara por transparencia
      (podes agregar tu propio criterio de nodata si lo necesitas, ej.
      descartar el valor minimo exacto si sabes que asi lo marca el OHMC).
    - El valor de gris (banda L, o el promedio de RGB si viniera en color)
      se interpreta como una codificacion LINEAL 0-255 entre vmin y vmax.
    - invert=True: usar cuando el backend codifica al reves de lo
      esperado (gris=0 -> valor MAXIMO, gris=255 -> valor MINIMO). Los
      sintomas tipicos de tener esto mal son "los ecos mas intensos se
      ven debiles" o viceversa. Ver diagnose.py para confirmar cual
      orientacion es la correcta con un frame real.
    """
    has_alpha = im.mode in ("LA", "RGBA")
    if im.mode not in ("L", "LA"):
        im = im.convert("RGBA" if has_alpha else "RGB")

    arr = np.array(im)

    if im.mode == "LA":
        gray = arr[..., 0].astype("float64")
        alpha = arr[..., 1]
    elif im.mode == "L":
        gray = arr.astype("float64")
        alpha = None
    elif im.mode == "RGBA":
        gray = arr[..., :3].mean(axis=-1)
        alpha = arr[..., 3]
    else:  # RGB
        gray = arr[..., :3].mean(axis=-1)
        alpha = None

    if invert:
        gray = 255.0 - gray

    values = vmin + (vmax - vmin) * (gray / 255.0)
    if alpha is not None:
        values = np.where(alpha == 0, np.nan, values)
    return values


def cog_to_grid(cog: CogMeta, timeout: int = 30, invert: bool | None = None) -> RadarGrid:
    """
    Baja la imagen grayscale del frame y la convierte en un RadarGrid con
    valores fisicos reales (dBZ, m/s, etc segun el producto), usando el
    rango oficial del producto (cog.cog_vmin/cog_vmax) para decodificar.

    invert: ver decode_grayscale_image(). Si no se pasa, usa
    config.GRAYSCALE_INVERTED (default False). Confirmar con
    diagnose.py antes de cambiarlo a ciegas.
    """
    if invert is None:
        try:
            import config as cfg
            invert = cfg.GRAYSCALE_INVERTED
        except (ImportError, AttributeError):
            invert = False

    im = fetch_frame_image(cog.id, colormap="grayscale", timeout=timeout)
    values = decode_grayscale_image(im, cog.cog_vmin, cog.cog_vmax, invert=invert)

    height, width = values.shape
    b = cog.bbox
    lon_1d = np.linspace(b["min_lon"], b["max_lon"], width)
    lat_1d = np.linspace(b["max_lat"], b["min_lat"], height)  # fila 0 = norte
    lon, lat = np.meshgrid(lon_1d, lat_1d)

    site_lon = (b["min_lon"] + b["max_lon"]) / 2
    site_lat = (b["min_lat"] + b["max_lat"]) / 2

    return RadarGrid(
        values=values, lon=lon, lat=lat, site_lon=site_lon, site_lat=site_lat,
        timestamp_utc=cog.observation_time, product=cog.product_key,
        elevation=str(cog.elevation_angle), units="", vcp=cog.strategy,
        radar_code=cog.radar_code,
    )


def fetch_latest_grid(radar_code: str, product_key: str, vol_nr=None, strategy=None):
    """Atajo: ultimo frame de un radar/producto, ya descargado como RadarGrid."""
    cog = get_latest_cog(radar_code, product_key, vol_nr=vol_nr, strategy=strategy)
    grid = cog_to_grid(cog)
    return grid, cog


# ------------------------------------------------------------------
# Diagnostico / verificacion
# ------------------------------------------------------------------
def verify_grayscale_decoding(cog: CogMeta, timeout: int = 30) -> None:
    """
    Chequeo de cordura mas profundo: baja la imagen grayscale de un frame,
    inspecciona los canales crudos, y prueba las 4 combinaciones posibles
    de decodificacion:
      - rango: cog_vmin/cog_vmax (fijo del producto) vs data_min/data_max
        (propio de este frame)
      - orientacion: normal (gris=0->min) vs invertida (gris=0->max)

    Ademas de comparar min/max contra lo que documenta el backend para
    ese frame, muestra percentiles (p10/p50/p90) para poder juzgar si la
    forma de la distribucion tiene sentido fisico (en una tormenta real,
    la mayor parte del area barrida NO deberia ser eco intenso).

    Uso:
        from radarplot.ohmc_client import get_latest_cog, verify_grayscale_decoding
        cog = get_latest_cog("RMA1", "DBZH")
        verify_grayscale_decoding(cog)
    """
    im = fetch_frame_image(cog.id, colormap="grayscale", timeout=timeout)
    arr = np.array(im.convert("RGBA") if im.mode != "RGBA" else im)

    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    mask = a != 0
    n_data = int(mask.sum())

    print(f"imagen: modo={im.mode} tamano={im.size}")
    print(f"pixeles con alpha!=0: {n_data} / {arr.shape[0]*arr.shape[1]}")
    print(f"cog.data_min={cog.data_min:.2f}  cog.data_max={cog.data_max:.2f}")
    print(f"cog.cog_vmin={cog.cog_vmin:.2f}  cog.cog_vmax={cog.cog_vmax:.2f}")

    if n_data == 0:
        print("ATENCION: ningun pixel con alpha!=0. Probemos sin filtrar "
              "por alpha (por si el nodata se marca distinto):")
        mask = np.ones(r.shape, dtype=bool)
        n_data = mask.size

    r_eq_g_eq_b = bool(np.array_equal(r[mask], g[mask]) and
                        np.array_equal(g[mask], b[mask]))
    print(f"¿R==G==B en los pixeles con dato? -> {r_eq_g_eq_b}")
    print(f"canal R crudo bajo mascara: min={r[mask].min()} max={r[mask].max()}\n")

    gray = r[mask].astype("float64")  # si R==G==B esto alcanza

    print(f"percentiles del canal gris crudo (0-255) bajo mascara: "
          f"p10={np.percentile(gray,10):.0f}  p50={np.percentile(gray,50):.0f}  "
          f"p90={np.percentile(gray,90):.0f}\n")

    for range_label, vmin, vmax in (
        ("cog_vmin/cog_vmax (rango fijo del producto)", cog.cog_vmin, cog.cog_vmax),
        ("data_min/data_max (rango propio de este frame)", cog.data_min, cog.data_max),
    ):
        for invert_label, invert in (("normal", False), ("INVERTIDO", True)):
            g = (255.0 - gray) if invert else gray
            values = vmin + (vmax - vmin) * (g / 255.0)
            ok = (abs(values.min() - cog.data_min) < 3 and
                  abs(values.max() - cog.data_max) < 3)
            p10, p50, p90 = np.percentile(values, [10, 50, 90])
            print(f"--- {range_label} / {invert_label}")
            print(f"    decodificado: min={values.min():.2f}  max={values.max():.2f}  "
                  f"(coincide con data_min/max? {'SI' if ok else 'no'})")
            print(f"    percentiles: p10={p10:.1f}  p50={p50:.1f}  p90={p90:.1f}")
            print(f"    -> si p50 esta MUY cerca de data_max, sospechar que esta "
                  f"orientacion esta al reves (la mayoria del area no deberia "
                  f"ser eco intenso)\n")
