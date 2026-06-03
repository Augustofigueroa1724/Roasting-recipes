# SCHEMA.md — FASE 0 (captura de esquema) ✅ DESBLOQUEADA

**Estado: COMPLETADA.** Esquema capturado con datos reales (HTTP 200).
Fecha de captura: 2026-06-03. Evidencia real en `samples/`.

---

## TL;DR

El bloqueo era el **nombre del header de autenticación**, no el token.

- ❌ Suposición previa (errónea): el header era `api-token`.
- ✅ Real (confirmado en la doc oficial OpenAPI): el header es **`x-api-key`**.

Con `x-api-key: <token>`, `GET /api/v3/public/roasts` devuelve **200** con datos.
La API se llama oficialmente **"Aillio Public API 1.0.0"** (`description: "Public API for RoastWorld resources."`).

---

## Autenticación (verificada)

```
Header:  x-api-key: <TU_TOKEN>
```

Definido en el spec OpenAPI (`/openapi.json`) como:
```json
"securitySchemes": {
  "ApiTokenAuth": { "type": "apiKey", "in": "header", "name": "x-api-key" }
}
```
- Base de la API: `https://api.roast.world`
- El token se genera en **roast.world → Settings → API Tokens**.
- El token se lee de la variable de entorno `ROAST_API_TOKEN` (`.env`, fuera del repo).
- Doc interactiva: `https://api.roast.world/api-docs` (spec en `/openapi.json`).

---

## Endpoints disponibles (los 4 del spec)

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| GET | `/api/v3/public/roasts` | `x-api-key` | Lista paginada de tuestes |
| GET | `/api/v3/public/roasts/{id}` | `x-api-key` | Detalle de un tueste (incl. curvas) |
| GET | `/api/v3/public/beans` | `x-api-key` | Lista paginada de cafés verdes (beans) |
| GET | `/api/v3/public/beans/{id}` | `x-api-key` | Detalle de un café verde |

**Paginación** (en `roasts` y `beans`):
- `page` (query, int, default `1`, min `1`)
- `size` (query, int, default `20`, min `1`, **max `100`**)
- Respuesta envuelta: `{ page, size, total, totalPages, data: [...] }`

> Nota: con el token usado, `roasts` devolvió `total: 4` (es el contenido público
> asociado a esa cuenta/serial). El catálogo a indexar = lo que devuelva tu token.

---

## Esquema: LISTA `GET /api/v3/public/roasts` → `data[]`

Campos confirmados (OpenAPI + respuesta real en `samples/roasts_p1.json`):

| Campo | Tipo | Notas |
|---|---|---|
| `uid` | string | **ID del tueste** (se usa en `/roasts/{id}`) |
| `roastName` | string | requerido |
| `dateTime` | int64 | epoch ms — inicio del tueste |
| `updatedAt` | int64 | epoch ms |
| `weightGreen` | int | gramos verde (puede ser 0) |
| `weightRoasted` | int | gramos tostado |
| `totalRoastTime` | int | segundos |
| `preheatTemperature` | int | °C |
| `colorMeterScale` | string | opcional |
| `beanId` | string | opcional — enlaza con `beans` |
| `firstCrackTime` | float | segundos (solo en la lista) |
| `firstCrackTemp` | float | °C (solo en la lista) |
| `firstCrackIRTemp` | float | °C IBTS (solo en la lista) |
| `serialNumber` | int | nº de serie del tostador |
| `deviceType` | string | p.ej. `"bullet"` |

`required`: `uid, roastName, dateTime, updatedAt, weightGreen, weightRoasted, totalRoastTime, preheatTemperature, serialNumber`.

---

## Esquema: DETALLE `GET /api/v3/public/roasts/{id}`

Incluye todo lo de la lista (salvo los `firstCrack*` resumidos) **más las curvas
completas**. Muestra real (curvas recortadas) en `samples/roast_detail.json`.

| Campo | Tipo | Notas |
|---|---|---|
| `uid`, `roastName`, `dateTime`, `updatedAt` | — | igual que lista |
| `weightGreen`, `weightRoasted`, `totalRoastTime` | int | |
| `preheatTemperature` | number | |
| `beanChargeTemperature` | number | °C grano al cargar |
| `drumChargeTemperature` | number | °C tambor al cargar |
| `beanTemperature` | number[] | **curva** (1 pt/s aprox; muestra real: 1209 pts) |
| `ibtsTemperature` | number[] | curva sensor IBTS/IR |
| `beanDerivative` | number[] | curva RoR del grano |
| `ibtsDerivative` | number[] | curva RoR IBTS |
| `differentialAirPressure` | number[] | curva (puede venir vacía) |
| `exhaustFanBlowerRpm` | number[] | curva (puede venir vacía) |
| `actions` | object[] | eventos `{type, second, setting}` (Power/Blower/Drum…) |
| `humidity` | number | |
| `ambient` | number | |
| `ibtsAmbientTemp` | number | |
| `atmosphericPressure` | number | |
| `annotationComments` | (null en muestra) | notas |
| `colorMeterScale` | string | |
| `beanId` | string | enlaza con `beans` |
| `blendId` | string | si es mezcla |
| `indexYellowingStart` | int | índice en la curva; `0` = no marcado |
| `indexFirstCrackStart` | int | índice; `0` = no marcado |
| `indexFirstCrackEnd` | int | índice; `0` = no marcado |
| `indexSecondCrackStart` | int | índice; `0` = no marcado |
| `indexSecondCrackEnd` | int | índice; `0` = no marcado |
| `serialNumber` | int | |
| `deviceType` | string | |

> Los hitos (yellowing, 1C, 2C) se dan como **índice dentro de las curvas**, no como
> tiempo/temperatura directos: para obtener temp/tiempo, indexar en `beanTemperature`
> / `ibtsTemperature` con esos índices.

---

## Esquema: `GET /api/v3/public/beans` → `data[]`

(Del OpenAPI; pendiente muestra real con datos — con el token actual devolvió lista vacía.)

| Campo | Tipo | Notas |
|---|---|---|
| `beanId` | string | ID; enlaza con `roasts.beanId` |
| `name` | string | |
| `country` | string | |
| `varieties` | string[] | |
| `tags` | string[] | |
| `process` | string | lavado/natural/honey… |
| `farm` | string | |
| `inStock` | int | gramos verde restantes (puede ser negativo) |
| `createdAt` | string | |

Todos `required` según el spec.

---

## Evidencia en `samples/`

- `openapi.json` — spec OpenAPI completo (fuente de verdad del esquema).
- `roasts_p1.json` — respuesta real 200 de `/public/roasts?page=1&size=2`.
- `roast_detail.json` — detalle real (curvas recortadas a 3 pts para legibilidad).
- `PROBE_RESULTS.json` / `roasts_p1.headers.txt` — sondas iniciales (header erróneo `api-token`, histórico).

---

## Búsqueda de comunidad (descubierta en FASE 2) — NO es la API pública

La búsqueda global de roast.world (la que da cientos de resultados) **no usa**
`x-api-key` ni la API pública. Usa un proxy a **Elasticsearch** con el **idToken de
Firebase** del usuario logueado:

```
POST https://api.roast.world/api/v3/proxy
Authorization: Bearer <idToken Firebase>      # NO el x-api-key
Content-Type: application/json
body: { "modelType": <enum>, "operation": "_search", "body": <query Elasticsearch> }
```

- **modelType (enum):** Bean=0, Profile=1, **Recipe=2**, Config=3, StashedRoast=4,
  StashedRecipe=5, … R2Profile=18, OfficialRecipe=19.
- **Respuesta:** formato Elasticsearch → `data.hits.hits[]` con `_id`, `_score`, `_source`.
- **_source de una receta:** `name, country, process, roastDegree, weight,
  downloadCount, userId, referenceRoastUid, updatedAt`.
- **Query de "discover":** excluye `deleted:1` e `isPrivate:1`; búsqueda =
  `wildcard name:"<q>*"` + `multi_match best_fields fuzziness AUTO` sobre `name`;
  filtros por `country.keyword`, `process.keyword`, `roastDegree`, `deviceType`,
  rango `weight`; orden por `downloadCount` (popularidad) o `*.keyword`.
- **Token:** el `idToken` se obtiene del loader raíz de cualquier página `_app`
  (campo `root.token` en `window.__remixContext`), accesible mandando la cookie
  `__session` (sesión Firebase, ~7 días). El idToken capturado dura ~7 días.
  ⚠️ Es una credencial sensible: va en `.env` (`ROAST_FIREBASE_TOKEN`), nunca en el repo.

> Esto es lo que hay que usar para buscar en el catálogo global (FASE 2 ampliada /
> FASE 3 "otras fuentes"). La API pública `x-api-key` solo ve el contenido propio.

## Siguiente paso → FASE 1 (indexador)

Con el esquema fijado, el indexador puede:
1. Paginar `GET /public/roasts?page=N&size=100` con `x-api-key` hasta `totalPages`.
2. Persistir la lista (campos resumen) en `catalog.db` (en `.gitignore`).
3. Opcional: para cada `uid`, traer el detalle y guardar curvas/hitos.
4. Cruzar `beanId` con `/public/beans` para enriquecer origen/proceso.
