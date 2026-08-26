"""
Grupo TRP Meteorología — Backend de render de radar (wrapper de plot_radar.py)
================================================================================
Este servicio NO reemplaza tu script. Lo único que hace es:
  1) Ejecutarlo en loop, una vez por cada combinación radar+producto configurada.
  2) Guardar los PNG que ya genera en una carpeta servida por HTTP.
  3) Exponer un endpoint /api/latest que el panel HTML consulta para saber
     cuál es la imagen más reciente de cada radar+producto.

TODO OBLIGATORIO ANTES DE DEPLOYAR:
  - Ajustá CMD_TEMPLATE más abajo con los flags EXACTOS de tu script
    (nombres reales de --radar, --producto, --outdir, paleta, range-rings, etc).
  - Ajustá RADARS y PRODUCTS con los códigos que realmente querés generar.
  - Ajustá FILENAME_PATTERN si tu script nombra los archivos distinto a
    RADAR_PRODUCTO_YYYYMMDD_HHMMSS.png
"""

import os
import re
import glob
import shlex
import subprocess
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("trp-radar-backend")

# ============================================================================
# CONFIGURACIÓN — editá esta sección para que coincida con tu script real
# ============================================================================

# Carpeta donde plot_radar.py escribe los PNG. Podés pasarla por flag (--outdir)
# si tu script lo soporta, o hacer que tu script siempre escriba acá.
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "./images")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ruta al script (en el Dockerfile se copia a /app/plot_radar.py)
SCRIPT_PATH = os.environ.get("SCRIPT_PATH", "./plot_radar.py")

# Radares y productos a generar en cada ciclo. Achicá esta lista si tu VPS/plan
# gratuito de Render es chico — cada combinación es una ejecución de matplotlib+cartopy.
RADARS = os.environ.get("RADARS", "RMA2,RMA6,RMA1,RMA4,RMA8").split(",")
PRODUCTS = os.environ.get("PRODUCTS", "DBZHo,VRAD,COLMAX").split(",")

# Cada cuántos minutos se corre el ciclo completo. La API de OHMC actualiza
# cada ~10 minutos, así que no tiene sentido correr esto más seguido que eso.
CYCLE_MINUTES = int(os.environ.get("CYCLE_MINUTES", "10"))

# Timeout por ejecución individual del script (matplotlib+cartopy puede tardar).
RUN_TIMEOUT_SEC = int(os.environ.get("RUN_TIMEOUT_SEC", "90"))

# Cuántas imágenes viejas conservar por combinación radar+producto (limpieza de disco).
KEEP_LAST_N = int(os.environ.get("KEEP_LAST_N", "3"))

# Clave simple opcional para proteger el backend (no es seguridad real, es
# una traba básica). Dejar vacío ("") para desactivar.
API_KEY = os.environ.get("API_KEY", "").strip()

# --------------------------------------------------------------------------
# TODO: PLANTILLA DE COMANDO — reemplazá por los flags reales de tu script.
# Los placeholders {radar}, {producto}, {outdir} se completan automáticamente.
# Ejemplo de referencia (AJUSTAR):
#   python plot_radar.py --radar {radar} --producto {producto} --outdir {outdir}
#     --paleta pysteps --range-rings --padding 240
# --------------------------------------------------------------------------
CMD_TEMPLATE = os.environ.get(
    "CMD_TEMPLATE",
    "python plot_radar.py --palette NWS --radar RMA1 --product DBZHo --extra-ring 260"
)

# Patrón para reconocer los archivos generados: RADAR_PRODUCTO_YYYYMMDD_HHMMSS.png
FILENAME_RE = re.compile(
    r"^(?P<radar>[A-Z0-9]+)_(?P<producto>[A-Za-z0-9]+)_(?P<date>\d{8})_(?P<time>\d{6})\.png$"
)

# ============================================================================
# ESTADO EN MEMORIA
# ============================================================================
last_run_status = {"last_success": None, "last_error": None, "running": False}


def run_one(radar: str, producto: str) -> bool:
    cmd = CMD_TEMPLATE.format(
        script=SCRIPT_PATH, radar=radar, producto=producto, outdir=str(OUTPUT_DIR)
    )
    log.info("Generando %s/%s ...", radar, producto)
    t0 = datetime.now()
    try:
        result = subprocess.run(
            shlex.split(cmd),
            cwd=os.path.dirname(SCRIPT_PATH) or ".",
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_SEC,
        )
        elapsed = (datetime.now() - t0).total_seconds()
        if result.returncode != 0:
            log.warning("plot_radar.py falló para %s/%s (%.1fs): %s", radar, producto, elapsed, result.stderr[-500:])
            return False
        log.info("OK %s/%s (%.1fs)", radar, producto, elapsed)
        return True
    except subprocess.TimeoutExpired:
        log.warning("Timeout (%ss) generando %s/%s", RUN_TIMEOUT_SEC, radar, producto)
        return False
    except Exception as e:
        log.exception("Error inesperado generando %s/%s: %s", radar, producto, e)
        return False


def cleanup_old_files():
    """Conserva solo las últimas KEEP_LAST_N imágenes por radar+producto."""
    groups = {}
    for f in OUTPUT_DIR.glob("*.png"):
        m = FILENAME_RE.match(f.name)
        if not m:
            continue
        key = (m.group("radar"), m.group("producto"))
        groups.setdefault(key, []).append(f)
    for key, files in groups.items():
        files.sort(key=lambda p: p.name, reverse=True)
        for old in files[KEEP_LAST_N:]:
            try:
                old.unlink()
            except OSError:
                pass


def run_cycle():
    if last_run_status["running"]:
        log.info("Ciclo anterior todavía corriendo, se salta este disparo.")
        return
    last_run_status["running"] = True
    log.info("Iniciando ciclo de render: %d radares x %d productos", len(RADARS), len(PRODUCTS))
    ok_count, fail_count = 0, 0
    for radar in RADARS:
        for producto in PRODUCTS:
            if run_one(radar.strip(), producto.strip()):
                ok_count += 1
            else:
                fail_count += 1
    cleanup_old_files()
    last_run_status["running"] = False
    now = datetime.now(timezone.utc).isoformat()
    if ok_count > 0:
        last_run_status["last_success"] = now
    if fail_count > 0:
        last_run_status["last_error"] = f"{fail_count} fallos en el ciclo de {now}"
    log.info("Ciclo terminado: %d OK, %d fallos", ok_count, fail_count)


def find_latest(radar: str, producto: str):
    matches = []
    for f in OUTPUT_DIR.glob(f"{radar}_{producto}_*.png"):
        m = FILENAME_RE.match(f.name)
        if m:
            matches.append((m.group("date") + m.group("time"), f))
    if not matches:
        return None
    matches.sort(key=lambda t: t[0], reverse=True)
    return matches[0][1]


# ============================================================================
# APP
# ============================================================================
app = FastAPI(title="Grupo TRP Meteorología — Radar Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # el panel HTML puede vivir en cualquier dominio/local
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.mount("/images", StaticFiles(directory=str(OUTPUT_DIR)), name="images")


def check_key(x_api_key: str | None, key_qs: str | None = None):
    """Acepta la key por header (x-api-key, usado por el panel) o por query
    string (?key=..., útil para probar pegando la URL directo en el navegador)."""
    provided = (x_api_key or key_qs or "").strip()
    if API_KEY and provided != API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida (mandala por header x-api-key o ?key=TU_KEY en la URL)")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "last_success_utc": last_run_status["last_success"],
        "last_error": last_run_status["last_error"],
        "running": last_run_status["running"],
        "radars": RADARS,
        "products": PRODUCTS,
        "cycle_minutes": CYCLE_MINUTES,
    }


@app.get("/api/list")
def list_available(x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    check_key(x_api_key, key)
    out = []
    for radar in RADARS:
        for producto in PRODUCTS:
            f = find_latest(radar.strip(), producto.strip())
            out.append({
                "radar": radar.strip(),
                "producto": producto.strip(),
                "disponible": f is not None,
                "archivo": f.name if f else None,
            })
    return {"items": out}


@app.get("/api/latest")
def latest(radar: str, producto: str, x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    check_key(x_api_key, key)
    f = find_latest(radar.upper(), producto)
    if not f:
        raise HTTPException(status_code=404, detail=f"No hay imágenes generadas todavía para {radar}/{producto}")
    m = FILENAME_RE.match(f.name)
    return {
        "radar": m.group("radar"),
        "producto": m.group("producto"),
        "timestamp_utc": f"{m.group('date')}T{m.group('time')}Z",
        "url": f"/images/{f.name}",
    }


@app.get("/api/debug/files")
def debug_files(x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Diagnóstico: lista TODOS los .png que existen dentro de /app (recursivo),
    con su ruta completa y tamaño. Útil para encontrar dónde está escribiendo
    realmente el script cuando OUTPUT_DIR no coincide con la ubicación real."""
    check_key(x_api_key, key)
    found = []
    search_root = Path("/app")
    for f in search_root.rglob("*.png"):
        try:
            stat = f.stat()
            found.append({
                "path": str(f),
                "size_kb": round(stat.st_size / 1024, 1),
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        except OSError:
            continue
    found.sort(key=lambda x: x["modified_utc"], reverse=True)
    return {"output_dir_configured": str(OUTPUT_DIR), "total_encontrados": len(found), "archivos": found[:50]}


@app.post("/api/run-now")
def run_now(x_api_key: str | None = Header(default=None), key: str | None = Query(default=None)):
    """Dispara un ciclo manual (útil para probar el deploy antes de esperar el cron)."""
    check_key(x_api_key, key)
    run_cycle()
    return {"status": "ciclo ejecutado"}


scheduler = BackgroundScheduler()
scheduler.add_job(run_cycle, "interval", minutes=CYCLE_MINUTES, next_run_time=datetime.now())
scheduler.start()
