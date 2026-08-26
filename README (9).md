# Grupo TRP Meteorología — Backend de Radar (deploy sin tocar Linux)

Este paquete corre tu `plot_radar.py` en loop y lo expone por HTTP para que
el panel de nowcasting lo consuma, como si fuera una API de imágenes.

## 0. Antes de nada — editá `api.py`

Abrí `api.py` y ajustá la sección **CONFIGURACIÓN** arriba del archivo:

- `CMD_TEMPLATE`: poné el comando **exacto** que usás hoy a mano, con los
  flags reales de tu script (paleta, range-rings, padding, etc). Los
  placeholders `{radar}`, `{producto}`, `{outdir}` se completan solos.
- `RADARS` / `PRODUCTS`: qué combinaciones querés que se generen cada ciclo.
  Empezá con pocos (4-5 radares) para no sobrecargar el servidor; después
  escalás.
- `FILENAME_RE`: si tu script no nombra los archivos como
  `RMA2_DBZHo_20260731_211000.png`, ajustá esa expresión regular.

Poné tu script real en esta misma carpeta con el nombre `plot_radar.py`
(reemplazando el que no está incluido acá — este paquete no lo tiene, solo
el wrapper).

## 1. Crear cuenta en Render

Andá a [render.com](https://render.com), create account (podés usar tu
cuenta de GitHub para loguearte).

## 2. Subir esta carpeta a GitHub

No hace falta terminal Linux, se puede todo desde GitHub Desktop o la web:

1. Creá un repositorio nuevo en GitHub (puede ser privado).
2. Subí estos 4 archivos + tu `plot_radar.py` real + cualquier archivo
   auxiliar que necesite (shapefiles, configs).

## 3. Deploy en Render

1. En Render, **New → Blueprint**, elegí el repo que acabás de subir.
   Render va a detectar el `render.yaml` automáticamente.
2. Te va a pedir el valor de `API_KEY` (podés inventar cualquier clave
   larga, ej. `trp-radar-2026-x92kd`). Guardala, la vas a necesitar en el
   panel HTML.
3. Confirmá el deploy. La primera build tarda varios minutos (instala
   cartopy vía conda, que pesa).
4. Cuando termine vas a tener una URL pública tipo
   `https://trp-radar-backend.onrender.com`.

## 4. Probarlo

Abrí en el navegador:

```
https://TU-URL.onrender.com/api/health
```

Debería devolver un JSON con `"status":"ok"`. Si `last_success_utc` está en
`null`, esperá los `CYCLE_MINUTES` configurados (default 10 min) o disparalo
a mano:

```
curl -X POST https://TU-URL.onrender.com/api/run-now -H "x-api-key: TU_API_KEY"
```

Después probá:

```
https://TU-URL.onrender.com/api/latest?radar=RMA2&producto=DBZHo
```

Te va a devolver algo como:

```json
{
  "radar": "RMA2",
  "producto": "DBZHo",
  "timestamp_utc": "20260731T211000Z",
  "url": "/images/RMA2_DBZHo_20260731_211000.png"
}
```

## 5. Conectar con el panel HTML

En la pestaña **Doble Panel** del panel de nowcasting, pegá tu URL de
Render en el campo "URL del backend propio" y tu `API_KEY`. El panel va a
empezar a mostrar tus plots reales en vez de (o junto a) las capas de OHMC.

## Notas importantes

- **Plan gratuito de Render**: el servicio "se duerme" tras ~15 min sin
  tráfico, y mientras duerme el scheduler no corre. Para nowcasting en
  vivo necesitás el plan **Starter** (siempre activo, ~7 USD/mes) o
  equivalente.
- **Disco**: las imágenes se guardan en el disco del contenedor, que se
  reinicia en cada deploy nuevo (no es un problema porque igual se
  regeneran cada `CYCLE_MINUTES`).
- **Carga del servidor**: cada combinación radar+producto es una ejecución
  completa de matplotlib+cartopy. 5 radares x 3 productos = 15 ejecuciones
  por ciclo. Si tu script tarda ~5-10s por imagen, un ciclo completo puede
  tardar 1-2 minutos — quedate dentro de ese margen para no atrasarte
  respecto al `CYCLE_MINUTES` configurado.
