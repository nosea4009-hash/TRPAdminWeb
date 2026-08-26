# -*- coding: utf-8 -*-
"""
plot_radar.py
=============
Script principal. Genera un plot ESTATICO de radar con el mismo estilo
visual que la imagen de referencia (Parana-INTA VRAD PPI0.5):

  - Fondo del mapa negro, figura en gris claro
  - Colormap de radar via paleta .pal customizable (WXTools.org)
  - Opacidad de radar 100%
  - Limites provinciales y departamentales (geojson provistos)
  - Etiquetas de ciudad en DejaVu Sans (no monoespaciada)
  - Titulo y colorbar en DejaVu Sans Mono ("Book" = peso regular del font)
  - Avisos a Muy Corto Plazo (ACP) del SMN en naranja fino, con recuadro
    "Avisos Meteorologicos a Muy Corto Plazo" estilo INTA

Modos de uso:
  python plot_radar.py --demo
      Datos sinteticos, para validar el estilo sin pegarle a la API.

  python plot_radar.py --live
      Ultimo frame disponible para RADAR_CODE/PRODUCT_KEY (config.py).

  python plot_radar.py --live --radar RMA4 --product COLMAXo
      Idem, sobreescribiendo radar/producto puntualmente.

  python plot_radar.py --list --radar RMA1
      Lista los productos/frames disponibles para ese radar (debug).

Ver config.py para TODOS los parametros editables (radar, producto,
paleta, colores, fuentes, ACP, etc).

NOTA: el modo --live todavia depende de resolver COG_BASE_URL_CANDIDATES
en config.py (la URL real para descargar el .tif a partir del file_path
relativo que devuelve la API). Ver el TODO en config.py / ohmc_client.py.
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
from matplotlib.image import imread

import config as cfg
from radarplot.pal_parser import load_pal, load_pal_discrete
from radarplot.metpy_palette import load_metpy_colortable
from radarplot.boundaries import plot_provinces, plot_departments, provinces_near
from radarplot.title import build_title, product_abbrev_and_units
from radarplot.ohmc_client import (
    RadarGrid, get_latest_cog, cog_to_grid, list_cogs,
    find_cog_nearest, list_cogs_in_range,
)

matplotlib.rcParams["font.family"] = cfg.FONT_SANS
matplotlib.rcParams["axes.unicode_minus"] = False


# ------------------------------------------------------------------
# Datos sinteticos (modo --demo): reproducen forma + rango de valores
# de la imagen de referencia para poder validar visualmente el estilo
# sin depender de la API del OHMC.
# ------------------------------------------------------------------
def make_demo_grid() -> RadarGrid:
    n = 500
    half = cfg.MAX_RANGE_KM / 111.0
    lon = np.linspace(cfg.SITE_LON_DEMO - half, cfg.SITE_LON_DEMO + half, n)
    lat = np.linspace(cfg.SITE_LAT_DEMO - half, cfg.SITE_LAT_DEMO + half, n)
    lon2d, lat2d = np.meshgrid(lon, lat)

    dx = (lon2d - cfg.SITE_LON_DEMO) * 111.0 * np.cos(np.radians(cfg.SITE_LAT_DEMO))
    dy = (lat2d - cfg.SITE_LAT_DEMO) * 111.0
    r = np.sqrt(dx**2 + dy**2)
    az = np.degrees(np.arctan2(dx, dy)) % 360

    rng = np.random.default_rng(3)
    values = np.full((n, n), np.nan)

    # Patron tipo "dipolo" doppler: acercamiento/alejamiento segun azimut
    base = 20 * np.sin(np.radians(az)) * (1 - r / cfg.MAX_RANGE_KM)
    noise = rng.normal(0, 3, (n, n))
    field = base + noise

    mask = (r < cfg.MAX_RANGE_KM) & (rng.random((n, n)) > 0.35)
    values[mask] = np.clip(field[mask], -40, 40)
    values[r > cfg.MAX_RANGE_KM] = np.nan

    return RadarGrid(
        values=values, lon=lon2d, lat=lat2d,
        site_lon=cfg.SITE_LON_DEMO, site_lat=cfg.SITE_LAT_DEMO,
        timestamp_utc=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        product="VRADo", elevation="0.5", units=cfg.UNITS_DEMO,
        vcp=cfg.VCP_DEMO, radar_code="DEMO",
    )


# ------------------------------------------------------------------
# Datos reales (modo --live)
# ------------------------------------------------------------------
def make_live_grid(radar_code: str, product_key: str, invert=None):
    cog = get_latest_cog(radar_code, product_key, vol_nr=cfg.VOL_NR,
                          strategy=cfg.STRATEGY)
    grid = cog_to_grid(cog, invert=invert)
    return grid, cog


def make_historical_grid(radar_code: str, product_key: str,
                          target_utc: _dt.datetime, search_window_days: float = 15,
                          invert=None):
    """Busca el frame disponible mas cercano a target_utc (hasta
    search_window_days para cada lado) y lo baja como RadarGrid."""
    cog = find_cog_nearest(radar_code, product_key, target_utc,
                            search_window_days=search_window_days)
    grid = cog_to_grid(cog, invert=invert)
    return grid, cog


def load_cities(path):
    cities = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cities.append((row["nombre"], float(row["lon"]), float(row["lat"])))
    return cities


def draw_acp(ax, avisos, color, linewidth):
    """Dibuja SOLO los poligonos de los avisos vigentes (naranja fino).
    El badge/leyenda de la esquina se dibuja aparte, siempre, con
    draw_acp_badge (ver mas abajo)."""
    for aviso in avisos:
        if not aviso.polygon:
            continue
        xs = [p[0] for p in aviso.polygon]
        ys = [p[1] for p in aviso.polygon]
        ax.plot(xs, ys, color=color, linewidth=linewidth, zorder=8,
                 solid_capstyle="round")


def draw_acp_badge(ax, badge_path, zoom):
    """
    Coloca la imagen fija "Avisos Meteorologicos a Muy Corto Plazo" en
    la esquina inferior izquierda del panel del radar, chica, igual que
    en la imagen de referencia de INTA. Se muestra siempre (no depende
    de si hay algun aviso activo en ese momento).
    """
    img = imread(str(badge_path))
    imagebox = OffsetImage(img, zoom=zoom)
    imagebox.image.axes = ax
    ab = AnnotationBbox(
        imagebox, (0.012, 0.02), xycoords="axes fraction",
        box_alignment=(0, 0), frameon=False, zorder=20, pad=0,
    )
    ax.add_artist(ab)


def draw_extra_ring(ax, site_lon, site_lat, ring_km, color, linestyle,
                     linewidth, alpha):
    """Anillo adicional a una distancia fija (independiente del alcance
    real del radar), util como referencia constante entre radares."""
    radius_deg = ring_km / 111.0
    ring = Circle((site_lon, site_lat), radius_deg, transform=ax.transData,
                  fill=False, edgecolor=color, linewidth=linewidth,
                  linestyle=linestyle, alpha=alpha, zorder=6)
    ax.add_patch(ring)


def render(grid: RadarGrid, acp_avisos, out_path, max_range_km=None,
           localidad=None, organismo=None, producto_abrev=None,
           unidad=None, pal_file=None, discrete=None, mostrar_ciudades=None,
           padding=None, extra_ring_km=None, mostrar_badge=None, palette=None,
           palette_start=None, palette_step=None, zoom_km=None):
    max_range_km = max_range_km or cfg.MAX_RANGE_KM
    discrete = cfg.PAL_DISCRETE if discrete is None else discrete
    mostrar_ciudades = cfg.SHOW_CITIES if mostrar_ciudades is None else mostrar_ciudades
    padding = cfg.MAP_PADDING_FACTOR if padding is None else padding
    extra_ring_km = cfg.EXTRA_RING_KM if extra_ring_km is None else extra_ring_km
    mostrar_badge = cfg.SHOW_ACP_BADGE if mostrar_badge is None else mostrar_badge
    zoom_km = cfg.DEFAULT_ZOOM_KM if zoom_km is None else zoom_km

    if localidad is None or organismo is None:
        nombre_default, organismo_default = cfg.RADAR_NAMES.get(
            grid.radar_code, (grid.radar_code, "SINARAME")
        )
        localidad = localidad or nombre_default
        organismo = organismo or organismo_default

    if producto_abrev is None or unidad is None:
        elev = float(grid.elevation) if grid.elevation not in (None, "") else None
        abrev_auto, unidad_auto = product_abbrev_and_units(grid.product, elev)
        producto_abrev = producto_abrev or abrev_auto
        unidad = unidad or grid.units or unidad_auto

    # Prioridad de paleta: --palette (con nombre, ej "NWS" de MetPy) >
    # --pal (archivo .pal propio) > paleta automatica segun unidad.
    if palette:
        spec = cfg.METPY_PALETTES.get(palette.upper())
        if spec is None:
            opciones = ", ".join(cfg.METPY_PALETTES)
            raise ValueError(
                f"Paleta con nombre desconocida: {palette!r}. "
                f"Opciones disponibles: {opciones}"
            )
        start = spec["start"] if palette_start is None else palette_start
        step = spec["step"] if palette_step is None else palette_step
        cmap, norm = load_metpy_colortable(spec["table"], start, step)
        unidad = unidad or spec["units"]
    else:
        # La paleta se elige segun la unidad (dBZ vs m/s) SALVO que se
        # haya pasado --pal explicitamente: asi no se mezcla la escala
        # de velocidad con la de reflectividad (o viceversa) por accidente.
        if pal_file is None:
            pal_file = cfg.PAL_FILES_BY_UNIT.get(unidad, cfg.PAL_FILE_FALLBACK)
        cmap, norm, meta = (load_pal_discrete(pal_file) if discrete
                             else load_pal(pal_file))
        unidad = unidad or meta.units or ""

    dt_utc = _dt.datetime.fromisoformat(grid.timestamp_utc.replace("Z", "+00:00"))
    titulo = build_title(localidad, organismo, producto_abrev, unidad,
                          dt_utc, vcp=grid.vcp)

    fig = plt.figure(figsize=(11, 11.4), dpi=150, facecolor=cfg.FIG_FACECOLOR)
    ax = fig.add_axes([0.045, 0.035, 0.80, 0.88])
    cax = fig.add_axes([0.875, 0.06, 0.035, 0.83])

    half = max_range_km / 111.0            # radio real del radar (para el anillo)
    if zoom_km:
        half_view = zoom_km / 111.0        # radio visible FIJO, ignora padding
    else:
        half_view = half * padding         # radio visible = alcance real +- margen
    ax.set_facecolor(cfg.MAP_FACECOLOR)
    ax.set_xlim(grid.site_lon - half_view, grid.site_lon + half_view)
    ax.set_ylim(grid.site_lat - half_view, grid.site_lat + half_view)
    ax.set_aspect(1.0 / np.cos(np.radians(grid.site_lat)))
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    # --- radar (opacidad 100%) ---
    ax.pcolormesh(grid.lon, grid.lat, grid.values, cmap=cmap, norm=norm,
                  shading="auto", alpha=cfg.RADAR_OPACITY, zorder=3)

    # --- limites departamentales y provinciales ---
    # se busca en un radio que cubra el area VISIBLE realmente en
    # pantalla (con padding o con zoom_km, lo que corresponda), y
    # tambien el anillo extra fijo si es mas grande que la vista.
    radio_busqueda_km = max(half_view * 111.0, extra_ring_km or 0)
    provincias_relevantes = provinces_near(cfg.PROVINCIAS_GEOJSON,
                                            grid.site_lon, grid.site_lat,
                                            radio_busqueda_km)
    plot_departments(ax, cfg.DEPARTAMENTOS_GEOJSON,
                      provincia_filter=provincias_relevantes,
                      color=cfg.DEPARTMENT_COLOR,
                      linewidth=cfg.DEPARTMENT_LINEWIDTH)
    plot_provinces(ax, cfg.PROVINCIAS_GEOJSON,
                    color=cfg.PROVINCE_COLOR,
                    linewidth=cfg.PROVINCE_LINEWIDTH)

    # --- anillo de alcance real ---
    ring = Circle((grid.site_lon, grid.site_lat), half, transform=ax.transData,
                  fill=False, edgecolor=cfg.RING_COLOR, linewidth=1.1, zorder=6)
    ax.add_patch(ring)

    # --- anillo extra fijo (referencia constante entre radares/productos) ---
    if extra_ring_km:
        draw_extra_ring(ax, grid.site_lon, grid.site_lat, extra_ring_km,
                         cfg.EXTRA_RING_COLOR, cfg.EXTRA_RING_LINESTYLE,
                         cfg.EXTRA_RING_LINEWIDTH, cfg.EXTRA_RING_ALPHA)

    # --- ciudades (activar/desactivar con SHOW_CITIES / --no-cities) ---
    if mostrar_ciudades:
        for nombre, lon, lat in load_cities(cfg.CIUDADES_CSV):
            if not (ax.get_xlim()[0] <= lon <= ax.get_xlim()[1] and
                    ax.get_ylim()[0] <= lat <= ax.get_ylim()[1]):
                continue
            ax.plot(lon, lat, marker="o", markersize=1.8,
                    color=cfg.CITY_MARKER_COLOR, zorder=9)
            ax.text(lon + 0.02, lat + 0.02, nombre, fontsize=cfg.CITY_FONT_SIZE,
                    color=cfg.CITY_LABEL_COLOR, fontfamily=cfg.FONT_MONO,
                    fontweight=cfg.CITY_FONT_WEIGHT, zorder=9)

    # --- ACP: poligonos de avisos vigentes (condicional) ---
    if cfg.MOSTRAR_ACP and acp_avisos:
        draw_acp(ax, acp_avisos, cfg.ACP_COLOR, cfg.ACP_LINEWIDTH)

    # --- badge "Avisos Meteorologicos a Muy Corto Plazo" (siempre, salvo
    #     que se desactive con SHOW_ACP_BADGE/--no-badge) ---
    if mostrar_badge and cfg.ACP_BADGE_PATH.exists():
        draw_acp_badge(ax, cfg.ACP_BADGE_PATH, cfg.ACP_BADGE_ZOOM)

    # --- titulo ---
    fig.text(0.045, 0.955, titulo, fontsize=cfg.TITLE_FONT_SIZE,
              fontfamily=cfg.FONT_MONO, color="black", ha="left", va="bottom")

    # --- colorbar ---
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    cb = fig.colorbar(sm, cax=cax)
    cb.ax.tick_params(labelsize=12, colors="black")
    for label in cb.ax.get_yticklabels():
        label.set_fontfamily(cfg.FONT_MONO)
    cb.outline.set_edgecolor("black")
    cb.outline.set_linewidth(1.0)

    fig.savefig(out_path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Plot estatico de radar OHMC")
    parser.add_argument("--demo", action="store_true",
                         help="Usar datos sinteticos para validar el estilo")
    parser.add_argument("--live", action="store_true",
                         help="Traer el ultimo frame real de la API del OHMC")
    parser.add_argument("--at", default=None,
                         help="Traer el frame historico mas cercano a esta "
                              "fecha/hora UTC (ISO 8601, ej "
                              "2026-07-25T14:30:00Z). Busca hasta "
                              "--search-window dias para cada lado.")
    parser.add_argument("--days-ago", type=float, default=None,
                         help="Atajo de --at: frame mas cercano a 'ahora "
                              "menos N dias'. Ej --days-ago 5")
    parser.add_argument("--search-window", type=float, default=15,
                         help="Ventana de busqueda en dias para --at/"
                              "--days-ago (default: 15)")
    parser.add_argument("--list-range", default=None,
                         help="Debug: listar frames entre dos fechas ISO "
                              "separadas por coma, ej "
                              "--list-range 2026-07-20T00:00:00Z,2026-07-25T00:00:00Z")
    parser.add_argument("--list", action="store_true",
                         help="Listar COGs disponibles para --radar (debug)")
    parser.add_argument("--radar", default=None,
                         help="radar_code (ej RMA1). Default: config.RADAR_CODE")
    parser.add_argument("--product", default=None,
                         help="product_key (ej DBZH, VRADo). "
                              "Default: config.PRODUCT_KEY")
    parser.add_argument("--pal", default=None, help="Ruta a paleta .pal custom")
    parser.add_argument("--palette", default=None,
                         help="Paleta con nombre (no archivo). Por ahora: "
                              "NWS = NWSReflectivityExpanded de MetPy "
                              "(-30 a 85 dBZ cada 5, recalibrada para que "
                              "los ecos intensos lleguen a rojo/magenta). "
                              "Tiene prioridad sobre --pal y la paleta "
                              "automatica.")
    parser.add_argument("--palette-start", type=float, default=None,
                         help="Override del valor inicial de --palette "
                              "(ej --palette-start -30). Util para correr "
                              "la escala y que los valores intensos lleguen "
                              "a los colores mas vivos de la tabla.")
    parser.add_argument("--palette-step", type=float, default=None,
                         help="Override del paso entre colores de --palette "
                              "(ej --palette-step 5)")
    parser.add_argument("--discrete", action="store_true",
                         help="Forzar colormap escalonado (no degrade)")
    parser.add_argument("--invert", dest="invert", action="store_true",
                         default=None,
                         help="Invertir la orientacion del decodificado "
                              "grayscale (gris=0 -> valor MAXIMO en vez de "
                              "minimo). Usar si los ecos intensos aparecen "
                              "debiles (o viceversa). Default: "
                              "config.GRAYSCALE_INVERTED")
    parser.add_argument("--no-invert", dest="invert", action="store_false",
                         help="Forzar orientacion normal (anula "
                              "config.GRAYSCALE_INVERTED si estuviera en True)")
    parser.add_argument("--no-acp", action="store_true",
                         help="No descargar/mostrar avisos ACP")
    parser.add_argument("--no-cities", action="store_true",
                         help="No mostrar etiquetas de ciudad")
    parser.add_argument("--padding", type=float, default=None,
                         help="Cuanto mapa mostrar mas alla del anillo del "
                              "radar (1.0=solo hasta el anillo, 1.3=30%% "
                              "mas de area). Default: config.MAP_PADDING_FACTOR. "
                              "Se ignora si se pasa --zoom-km.")
    parser.add_argument("--zoom-km", type=float, default=None,
                         help="Radio FIJO (km) de lo que se ve en pantalla, "
                              "independiente del alcance real del radar/frame "
                              "(que puede variar segun el producto/estrategia "
                              "de barrido, ej 480km en vez de 240km). El "
                              "anillo real y el extra se siguen dibujando en "
                              "su radio verdadero. Ej: --zoom-km 240")
    parser.add_argument("--extra-ring", type=float, default=None,
                         help="Radio (km) de un segundo anillo fijo de "
                              "referencia, ademas del anillo real del radar. "
                              "0 para desactivarlo. Default: config.EXTRA_RING_KM")
    parser.add_argument("--no-badge", action="store_true",
                         help="No mostrar el badge 'Avisos Meteorologicos "
                              "a Muy Corto Plazo' de la esquina")
    parser.add_argument("--out", default=None, help="Ruta del PNG de salida")
    args = parser.parse_args()

    radar_code = args.radar or cfg.RADAR_CODE
    product_key = args.product or cfg.PRODUCT_KEY

    if args.list:
        cogs = list_cogs(radar_code=radar_code)
        for c in cogs:
            print(f"{c.radar_code:6s} {c.product_key:8s} {c.observation_time} "
                  f"elev={c.elevation_angle:<5} vol_nr={c.vol_nr} "
                  f"strategy={c.strategy} file_path={c.file_path}")
        return

    if args.list_range:
        start_s, end_s = args.list_range.split(",")
        start = _dt.datetime.fromisoformat(start_s.strip().replace("Z", "+00:00"))
        end = _dt.datetime.fromisoformat(end_s.strip().replace("Z", "+00:00"))
        cogs = list_cogs_in_range(radar_code, product_key, start, end)
        print(f"{len(cogs)} frames encontrados entre {start} y {end}:\n")
        for c in cogs:
            print(f"  id={c.id:<8} {c.observation_time}")
        return

    # --- resolver la fecha/hora buscada (si es que se pidio historico) ---
    target_utc = None
    if args.at:
        target_utc = _dt.datetime.fromisoformat(args.at.replace("Z", "+00:00"))
    elif args.days_ago is not None:
        target_utc = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=args.days_ago)
    is_historical = target_utc is not None
    is_real = args.live or is_historical

    cfg.OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

    max_range_km = None
    if is_historical:
        grid, cog = make_historical_grid(radar_code, product_key, target_utc,
                                          search_window_days=args.search_window,
                                          invert=args.invert)
        max_range_km = cog.radar_coverage_m / 1000.0
        print(f"Frame encontrado: {cog.observation_time} "
              f"(pedido: {target_utc.isoformat()})")
    elif args.live:
        grid, cog = make_live_grid(radar_code, product_key, invert=args.invert)
        max_range_km = cog.radar_coverage_m / 1000.0
    else:
        grid = make_demo_grid()

    acp_avisos = []
    if not args.no_acp and cfg.MOSTRAR_ACP:
        try:
            from radarplot.acp_smn import fetch_acp_polygons
            acp_avisos = fetch_acp_polygons(cfg.ACP_RSS_URL)
        except Exception as exc:  # sin conexion, feed caido, etc.
            print(f"[ACP] no se pudieron descargar los avisos: {exc}")

    ts = _dt.datetime.fromisoformat(grid.timestamp_utc.replace("Z", "+00:00"))
    out_path = args.out or (cfg.OUTPUT_DIR /
                             f"{grid.radar_code}_{grid.product}_{ts:%Y%m%d_%H%M%S}.png")

    render(grid, acp_avisos, out_path, max_range_km=max_range_km,
           localidad=(cfg.SITE_NAME_DEMO if not is_real else None),
           organismo=(cfg.ORGANISMO_DEMO if not is_real else None),
           producto_abrev=(cfg.PRODUCT_ABREV_DEMO if not is_real else None),
           unidad=(cfg.UNITS_DEMO if not is_real else None),
           pal_file=args.pal, palette=args.palette, discrete=args.discrete,
           palette_start=args.palette_start, palette_step=args.palette_step,
           mostrar_ciudades=(False if args.no_cities else None),
           padding=args.padding, extra_ring_km=args.extra_ring,
           mostrar_badge=(False if args.no_badge else None),
           zoom_km=args.zoom_km)
    print(f"Listo -> {out_path}")


if __name__ == "__main__":
    main()
