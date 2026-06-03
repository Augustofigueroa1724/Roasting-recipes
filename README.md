# Roasting-recipes

Catálogo y buscador de **recetas de tueste de café** sobre los datos de
[roast.world](https://roast.world) (Aillio). Permite buscar en el catálogo
global de la comunidad por criterios cerrados (origen, proceso, nivel de tueste…)
y **comparar el perfil de tueste** (Power 1–9 y curva de temperatura) de varias
recetas para ver de un vistazo si son parecidas o cuál se separa.

> El esquema de datos y los endpoints (incl. los no documentados) están en
> [`SCHEMA.md`](SCHEMA.md).

## Estado del proyecto (fases)

| Fase | Qué hace | Estado |
|------|----------|--------|
| 0 | Captura del esquema de la API | ✅ |
| 1 | Indexador de **tu** catálogo propio → `catalog.db` (`roast_index.py`) | ✅ |
| 2 | Buscador del catálogo **global** de comunidad (`serve.py` + `community.py` + `web/`) | ✅ |
| 2.5 | Comparativa de perfiles de Power/temperatura entre recetas | ✅ |
| 3 | 0 resultados → buscar en otras fuentes → archivo importable a roast.world/RoasTime | ⏳ pendiente |

## Cómo funciona (fuentes de datos)

Hay **tres** vías de acceso a roast.world, descubiertas en FASE 0/2 (detalle en `SCHEMA.md`):

1. **API pública** (`GET /api/v3/public/roasts|beans`, cabecera `x-api-key`) — solo
   da **tu** contenido. La usa `roast_index.py` (FASE 1).
2. **Proxy a Elasticsearch** (`POST /api/v3/proxy`, `Authorization: Bearer <idToken>`) —
   el catálogo **global** de recetas. Lo usa el buscador (FASE 2).
3. **Firebase Storage** (URL pública, sin auth) — el **log completo** de cada tueste
   (curvas + acciones de Power/Fan/Drum). Lo usa la comparativa (FASE 2.5); la URL se
   resuelve vía el proxy (índice de roasts, campo `url`).

## Configuración

Copia `.env.example` a `.env` y rellena:

```bash
cp .env.example .env
```

- `ROAST_API_TOKEN` — token personal de la API pública
  (roast.world → Settings → API Tokens). Cabecera `x-api-key`. Solo FASE 1.
- `ROAST_FIREBASE_TOKEN` — idToken de Firebase de tu sesión en roast.world.
  Necesario para el buscador y la comparativa (FASE 2/2.5). **Caduca ~7 días.**
  Se obtiene del campo `root.token` de `window.__remixContext` en cualquier
  página `/recipes` estando logueado (DevTools → buscar `__remixContext`).

`.env`, `catalog.db` y `.venv/` están en `.gitignore` (nunca se commitean).

Solo se usa la **librería estándar de Python** (sin dependencias que instalar).

## Uso

### Indexar tu catálogo propio (FASE 1)

```bash
python3 roast_index.py            # lista de roasts + beans -> catalog.db
python3 roast_index.py --detail   # además curvas/hitos de cada roast
python3 roast_index.py --stats    # resumen de lo indexado
```

### Buscador + comparativa (FASE 2 / 2.5)

```bash
python3 serve.py                  # http://localhost:8000
python3 serve.py --port 9000      # otro puerto
```

Abre `http://localhost:8000` (en Codespaces, pestaña **PORTS** → puerto 8000).

- Busca por **texto libre** o filtra por **origen / proceso / nivel de tueste / dispositivo**.
- Marca recetas con el **checkbox** (o **Seleccionar todo**) y pulsa **Comparar selección**.
- En el gráfico: pestañas **Power (1–9)** y **Temperatura**, líneas de **1er crack**,
  **resaltado** por leyenda (clic para fijar), **×** para quitar una receta, y un
  **resumen** que detecta cuál se separa más.

## Archivos

| Archivo | Rol |
|---------|-----|
| `roast_index.py` | Indexador de tu catálogo propio → SQLite (FASE 1) |
| `community.py` | Cliente del catálogo global: búsqueda, facetas y perfiles de tueste |
| `serve.py` | Servidor HTTP (stdlib): sirve la web y la API JSON |
| `web/index.html` | Interfaz de una página (vanilla JS + SVG, sin librerías) |
| `enrich.py` | Derivación de criterios del catálogo propio |
| `SCHEMA.md` | Esquema y endpoints (documentados y no documentados) |
| `samples/` | Respuestas reales de ejemplo + spec OpenAPI |

### Endpoints de la API local (`serve.py`)

- `GET /api/search?q=&country=&process=&level=&device=&sortBy=&size=` — búsqueda en comunidad
- `GET /api/facets` — valores disponibles para los filtros (agregaciones)
- `GET /api/roast/<uid>` — detalle de una receta
- `GET /api/profile/<uid>` — perfil de tueste (Power/Fan/Drum + curva + hitos)
- `GET /api/compare?uids=a,b,c` — perfiles de varias recetas para comparar
- `GET /api/local/search` — búsqueda en tu catálogo propio (`catalog.db`)

## Notas

- Los tokens (`ROAST_FIREBASE_TOKEN` y `ROAST_API_TOKEN`) **caducan**; si el buscador
  da error de autorización, renueva el token en `.env`.
- Los perfiles de tueste descargados se **cachean** en `catalog.db`
  (tabla `recipe_profiles`, TTL 7 días).
