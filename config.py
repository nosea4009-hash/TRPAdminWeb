# -*- coding: utf-8 -*-
"""
config.py
=========
Configuracion central del proyecto. Edita este archivo (no hace falta
tocar el resto del codigo) para adaptar rutas, radar, producto y estilo.
"""
from pathlib import Path

BASE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------
# 1) DATOS GEOGRAFICOS (ya provistos por vos)
# ---------------------------------------------------------------------
PROVINCIAS_GEOJSON = BASE_DIR / "data" / "ar.json"
DEPARTAMENTOS_GEOJSON = BASE_DIR / "data" / "departamentos.geojson"
CIUDADES_CSV = BASE_DIR / "data" / "ciudades.csv"

# ---------------------------------------------------------------------
# 2) RADAR / PRODUCTO (API real de OHMC: webmet.ohmc.ar)
# ---------------------------------------------------------------------
# Codigos reales tal cual los devuelve /api/v1/cogs?product_keys.
# Ejemplos de radar_code vistos en la API: RMA1, RMA3, RMA4, RMA5, RMA8,
# RMA9, RMA11, RMA12, RMA14, RMA15, RMA16, RMA17, AR8.
# Ejemplos de product_key: DBZH, DBZHo, COLMAX, COLMAXo, VRADo, WRADo.
#   DBZH/DBZHo  -> reflectividad (dBZ), PPI a la elevacion mas baja
#   COLMAX/o    -> reflectividad, maximo en columna (compuesto, sin PPI)
#   VRADo       -> velocidad radial Doppler (m/s)
#   WRADo       -> ancho espectral (m/s)
#   (sufijo "o" = variante filtrada/QC que usa el visor por defecto)
RADAR_CODE = "RMA1"
PRODUCT_KEY = "DBZH"

# Parametros opcionales para /cogs/latest (podes dejarlos como estan;
# el backend elige el primero que tenga datos disponibles)
VOL_NR = ["01", "02", "03"]
STRATEGY = ["0315", "1000"]

# Nombres conocidos de algunos radares SINARAME (fuente: SMN/INVAP). Los
# que no esten en este diccionario se muestran con su radar_code tal cual;
# agrega los que necesites.
RADAR_NAMES = {
    "RMA1": ("Córdoba", "SINARAME"),
    "RMA4": ("Resistencia", "SINARAME"),
    "RMA5": ("Bernardo de Irigoyen", "SINARAME"),
    "RMA8": ("Mercedes", "SINARAME"),
    # "AR8": ("Parana", "SINARAME / INTA"),  # <- verificar: el bbox real
    #   devuelto por la API para AR8 no coincide con Parana: confirmalo
    #   antes de usarlo (ver README, seccion "Nombres de radar").
}

MAX_RANGE_KM = 240.0               # radio del anillo blanco exterior
                                    # (se recalcula automaticamente en modo
                                    # --live a partir de radar_coverage_m)

# Cuanto mapa mostrar MAS ALLA del anillo de alcance del radar. 1.0 =
# el mapa termina justo en el borde del anillo (como antes). 1.3 =
# se ve un 30% mas de area alrededor. El anillo blanco se sigue
# dibujando en su lugar real; esto solo agranda el "zoom out" del mapa.
# Tambien se puede pasar por linea de comandos con --padding.
MAP_PADDING_FACTOR = 1.25

# ZOOM FIJO: algunos radares/productos/estrategias de barrido (ej RMA2
# en modo PPI0 con estrategia "0315", pensado para vigilancia de largo
# alcance) devuelven un radar_coverage_m real bastante mayor a lo
# habitual (480 km en vez de 240 km). Eso NO es un error: la API esta
# reportando el alcance real de ESE barrido puntual, no un valor fijo
# universal. Si preferis ver siempre un area fija en pantalla (por
# ejemplo, comparar radares a la misma escala) en vez de que la vista se
# ajuste al alcance real de cada frame, poné un valor aca (en km) o
# usa --zoom-km <N> por linea de comandos, que tiene prioridad. El
# anillo real y el anillo extra se siguen dibujando en su radio
# verdadero, esto solo cambia CUANTO SE VE en pantalla.
# None = usar MAP_PADDING_FACTOR sobre el alcance real (comportamiento
# por defecto, se adapta al alcance real de cada frame).
DEFAULT_ZOOM_KM = None

# Solo se usan en modo --demo (datos sinteticos, sin pegarle a la API)
SITE_NAME_DEMO = "Parana"
ORGANISMO_DEMO = "SINARAME / INTA"
SITE_LON_DEMO = -60.5238
SITE_LAT_DEMO = -31.7319
PRODUCT_ABREV_DEMO = "PPI0.5"
UNITS_DEMO = "m/s"
VCP_DEMO = "VCP1000.02"

# ---------------------------------------------------------------------
# 3) PALETA DE COLOR (.pal). Usa una de las incluidas o la tuya propia
#    (formato WXTools.org, ver radarplot/pal_parser.py). Tambien podes
#    generar una paleta de partida a partir del colormap oficial del
#    OHMC con radarplot.ohmc_client.colormap_info_to_pal(...).
#
#    La paleta se elige AUTOMATICAMENTE segun la unidad del producto
#    (dBZ vs m/s), para no mezclar la escala de velocidad con la de
#    reflectividad (o viceversa) sin querer. Si pasas --pal a mano,
#    eso siempre tiene prioridad sobre este mapeo.
# ---------------------------------------------------------------------
PAL_FILES_BY_UNIT = {
    "dBZ": BASE_DIR / "palettes" / "dBZ_default.pal",
    "m/s": BASE_DIR / "palettes" / "VRAD_default.pal",
}
PAL_FILE_FALLBACK = PAL_FILES_BY_UNIT["dBZ"]  # si la unidad no matchea ninguna
PAL_DISCRETE = False   # True = colormap escalonado, False = degrade continuo

# Paletas "con nombre" (no archivo .pal), tomadas de MetPy
# (metpy.plots.ctables). Se usan con --palette <alias>, y tienen
# PRIORIDAD sobre --pal / la paleta automatica por unidad. Facil de
# agregar mas alias: "table" es el nombre de la colortable de MetPy,
# "start"/"step" arman la escala fisica (ver radarplot/metpy_palette.py),
# y "units" se usa para el titulo si no se paso --unidad a mano.
METPY_PALETTES = {
    "NWS": {
        "table": "NWSReflectivityExpanded",
        # start=-30 (no -20): esta tabla reserva sus primeros 8 colores
        # (de los 23 totales) para el modo "aire claro" (-20 a 15 dBZ,
        # tonos grises/pasteles apagados a proposito). Con start=-20 el
        # techo real de una tormenta (~60-70 dBZ) caia en naranja, sin
        # llegar nunca al rojo oscuro/magenta reservados para 65-90.
        # Con start=-30 toda la escala se corre 10 dBZ, y un nucleo de
        # ~62 dBZ ya cae en rojo oscuro (antes: naranja), con magenta
        # reservado para 70+ (el techo real del producto DBZH).
        # Ajustable al vuelo con --palette-start / --palette-step.
        "start": -30.0,
        "step": 5.0,
        "units": "dBZ",
    },
}

# ---------------------------------------------------------------------
# 4) API OHMC (webmet.ohmc.ar) - confirmada
# ---------------------------------------------------------------------
OHMC_API_BASE = "https://webmet.ohmc.ar/api/v1"

# El dato se obtiene pidiendo la imagen "grayscale" de cada frame
# (GET /api/v1/frames/{id}/image.png?colormap=grayscale) y decodificando
# el nivel de gris (0-255) como una interpolacion lineal entre el rango
# oficial del producto (cog_vmin/cog_vmax). Ver radarplot/ohmc_client.py
# para el detalle completo.
#
# GRAYSCALE_INVERTED: si los ecos MAS INTENSOS aparecen como los valores
# MAS DEBILES en el plot (o viceversa), probablemente la imagen esta
# codificada al reves de lo esperado (gris=0 -> valor maximo, en vez de
# gris=0 -> valor minimo). Confirmalo con un frame real usando:
#     python diagnose.py --radar RMA1 --product DBZH
# (o --at/--days-ago para apuntar a un frame historico puntual) y despues
# poné True/False aca segun lo que haya dado.
GRAYSCALE_INVERTED = False

# ---------------------------------------------------------------------
# 5) ACP - Avisos a Muy Corto Plazo (SMN, feed CAP publico)
# ---------------------------------------------------------------------
ACP_RSS_URL = "https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml"
MOSTRAR_ACP = True
ACP_COLOR = "#f5a623"       # naranja amarillento, igual que la imagen de referencia
ACP_LINEWIDTH = 1.1         # fino

# Badge "Avisos Meteorologicos a Muy Corto Plazo" en la esquina inferior
# izquierda. Es una imagen fija (no se dibuja con texto), igual que en
# la imagen de referencia de INTA: se muestra SIEMPRE, este o no activo
# algun aviso en ese momento (funciona como leyenda/branding del
# producto, no como indicador puntual). Se puede apagar con
# SHOW_ACP_BADGE=False o --no-badge.
ACP_BADGE_PATH = BASE_DIR / "assets" / "acp_badge.png"
SHOW_ACP_BADGE = True
ACP_BADGE_ZOOM = 0.45       # tamano relativo (chico, como en la referencia)

# ---------------------------------------------------------------------
# 6) ANILLOS DE ALCANCE
# ---------------------------------------------------------------------
# Anillo "real": se dibuja siempre, al radio real del radar (MAX_RANGE_KM,
# que en modo --live se recalcula solo desde radar_coverage_m).
#
# Anillo EXTRA fijo: ademas del real, se puede dibujar un segundo anillo
# a una distancia fija (por defecto 240 km) como referencia constante
# entre distintos radares/productos que tengan alcances distintos.
# None o 0 para desactivarlo. Tambien configurable con --extra-ring.
EXTRA_RING_KM = 240.0
EXTRA_RING_COLOR = "#ffffff"
EXTRA_RING_LINESTYLE = "--"
EXTRA_RING_LINEWIDTH = 0.8
EXTRA_RING_ALPHA = 0.6

# ---------------------------------------------------------------------
# 7) ESTILO VISUAL (calcado de la imagen de referencia adjunta)
# ---------------------------------------------------------------------
FIG_FACECOLOR = "#e6e6e6"     # gris claro de fondo de figura
MAP_FACECOLOR = "#000000"     # panel del radar: negro
RING_COLOR = "#ffffff"        # anillo de alcance maximo
PROVINCE_COLOR = "#8c8c8c"
PROVINCE_LINEWIDTH = 0.9
DEPARTMENT_COLOR = "#797979"
DEPARTMENT_LINEWIDTH = 0.35

# Etiquetas de ciudad: activar/desactivar con SHOW_CITIES (o --no-cities
# por linea de comandos, que tiene prioridad si se pasa).
SHOW_CITIES = True
CITY_LABEL_COLOR = "#f2f2f2"
CITY_MARKER_COLOR = "#f2f2f2"
CITY_FONT_SIZE = 7
CITY_FONT_WEIGHT = "light"   # cae a "regular" si el font no tiene ese peso

TITLE_FONT_SIZE = 19
FONT_MONO = "DejaVu Sans Mono"   # usa el peso "Book" (= regular) del propio font
FONT_SANS = "DejaVu Sans"

RADAR_OPACITY = 1.0   # 100%

OUTPUT_DIR = BASE_DIR / "output"
CACHE_DIR = BASE_DIR / "cache"
