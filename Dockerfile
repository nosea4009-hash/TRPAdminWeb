# Grupo TRP Meteorología — imagen del backend de radar
# Usamos conda-forge como base porque cartopy necesita GEOS/PROJ compilados,
# y con pip solo eso suele fallar o requerir compilar de cero (muy lento).
FROM condaforge/miniforge3:latest

WORKDIR /app

# Dependencias científicas vía conda (rápido y sin compilar nada a mano).
# Agregá acá cualquier otra librería que use tu plot_radar.py (h5py, pyproj, etc).
RUN mamba install -y -c conda-forge \
    python=3.11 \
    matplotlib \
    cartopy \
    numpy \
    requests \
    pillow \
    && mamba clean -afy

# Dependencias del backend (FastAPI) vía pip, más liviano.
RUN pip install --no-cache-dir fastapi uvicorn[standard] apscheduler

# Copiá tu script real acá. Reemplazá "plot_radar.py" por el nombre real si difiere,
# y agregá cualquier archivo auxiliar que tu script necesite (shapefiles, config, etc).
COPY plot_radar.py /app/plot_radar.py
COPY api.py /app/api.py

# Si tu script usa archivos de estilo/shapefiles/config adicionales, agregalos así:
# COPY assets/ /app/assets/

ENV OUTPUT_DIR=/app/images
RUN mkdir -p /app/images

EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
