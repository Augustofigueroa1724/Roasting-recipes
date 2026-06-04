"""Búsqueda en el catálogo GLOBAL de recetas de roast.world (comunidad).

No usa la API pública (x-api-key); usa el proxy a Elasticsearch con el idToken de
Firebase del usuario. Esquema y mecanismo documentados en SCHEMA.md.

    POST https://api.roast.world/api/v3/proxy
    Authorization: Bearer <ROAST_FIREBASE_TOKEN>
    body: {modelType: 2 (Recipe), operation: "_search", body: <query ES>}

El token se lee de la variable de entorno ROAST_FIREBASE_TOKEN (.env, gitignored).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.error
import urllib.request

PROXY_URL = "https://api.roast.world/api/v3/proxy"
SITE_BASE = "https://roast.world"
PROFILE_DB = "catalog.db"          # cache de perfiles descargados
PROFILE_TTL = 7 * 24 * 3600        # 7 días
MODEL_RECIPE = 2  # enum modelType (ver SCHEMA.md)
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Etiquetas oficiales de roastDegree (extraídas del frontend de roast.world).
ROAST_DEGREE_LABELS = {
    0: "Very light (Cinnamon)",
    1: "Light (City)",
    2: "Medium light (City+)",
    3: "Medium (Full city)",
    4: "Medium dark (Full city+)",
    5: "Dark (Vienna)",
    6: "Very dark (French)",
}
ROAST_DEGREE_BY_LABEL = {v: k for k, v in ROAST_DEGREE_LABELS.items()}

# roast.world enruta las recetas públicas como /{handle}/recipes/{recipeId},
# donde {handle} es el handle público del autor (p.ej. "jambarodo.uCWZ" =
# username + "." + tag). El _id de la receta SOLO no basta: sin el handle la web
# de roast.world responde "unexpected error". El handle no aparece en el esquema
# documentado, así que lo buscamos en varios campos candidatos del _source.
_HANDLE_FIELDS = ("userHandle", "handle", "userSlug", "slug", "profileSlug", "publicHandle")
_USERNAME_FIELDS = ("userName", "username", "userUsername", "displayName")
_TAG_FIELDS = ("userTag", "tag", "userIdShort", "discriminator")


def public_handle(source: dict) -> str | None:
    """Deriva el handle público del autor desde el _source de una receta."""
    for f in _HANDLE_FIELDS:
        v = source.get(f)
        if isinstance(v, str) and v.strip() and "/" not in v:
            return v.strip()
    uname = next((source.get(f) for f in _USERNAME_FIELDS if isinstance(source.get(f), str) and source.get(f).strip()), None)
    tag = next((source.get(f) for f in _TAG_FIELDS if isinstance(source.get(f), str) and source.get(f).strip()), None)
    if uname and tag:
        return f"{uname.strip()}.{tag.strip()}"
    return None


def recipe_public_url(source: dict, recipe_id: str) -> str | None:
    """URL pública de la receta en roast.world, o None si no hay handle."""
    h = public_handle(source)
    return f"{SITE_BASE}/{h}/recipes/{recipe_id}" if h else None


class CommunityError(RuntimeError):
    pass


def token() -> str:
    t = os.environ.get("ROAST_FIREBASE_TOKEN", "").strip()
    if not t:
        raise CommunityError(
            "Falta ROAST_FIREBASE_TOKEN en .env. Es el idToken de Firebase de tu "
            "sesión en roast.world (campo root.token de window.__remixContext).")
    return t


def _post(body: dict, timeout: int = 30, retries: int = 2) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        PROXY_URL, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    last = None
    for attempt in range(1, retries + 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", "replace")[:200]
            if exc.code in (401, 403):
                raise CommunityError(
                    f"{exc.code} no autorizado. El ROAST_FIREBASE_TOKEN puede haber "
                    f"caducado (~7 días); renuévalo desde roast.world. ({payload})")
            if exc.code in (502, 503, 504) and attempt <= retries:
                last = CommunityError(f"{exc.code} gateway"); time.sleep(0.5 * attempt); continue
            raise CommunityError(f"HTTP {exc.code}: {payload}")
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt <= retries:
                time.sleep(0.5 * attempt); continue
    raise CommunityError(f"fallo de red tras reintentos: {last}")


# --------------------------------------------------------------------------- #
# Búsqueda
# --------------------------------------------------------------------------- #
def _build_query(p: dict) -> dict:
    """Construye el query Elasticsearch replicando la búsqueda 'discover' del front."""
    must: list = []
    must_not = [{"term": {"deleted": 1}}, {"term": {"isPrivate": 1}}]  # solo públicas, no borradas
    bool_q: dict = {"must_not": must_not}

    q = (p.get("q") or "").strip()
    if q:
        bool_q["minimum_should_match"] = 1
        bool_q["should"] = [
            {"wildcard": {"name": f"{q}*"}},
            {"multi_match": {"lenient": True, "query": q, "type": "best_fields",
                             "fields": ["name"], "fuzziness": "AUTO",
                             "analyzer": "standard", "operator": "AND"}},
        ]

    if p.get("country"):
        must.append({"match": {"country.keyword": p["country"]}})
    if p.get("process"):
        must.append({"match": {"process.keyword": p["process"]}})
    if p.get("device"):
        must.append({"match": {"deviceType": p["device"]}})
    level = p.get("level")
    if level not in (None, ""):
        deg = ROAST_DEGREE_BY_LABEL.get(level, level)
        try:
            must.append({"match": {"roastDegree": int(deg)}})
        except (TypeError, ValueError):
            pass
    if must:
        bool_q["must"] = must

    size = int(p.get("size", 24))
    frm = int(p.get("from", 0))
    sort_field = p.get("sortBy", "popularity")
    sort = {"downloadCount": "desc"} if sort_field == "popularity" else {sort_field: "desc"}

    return {"size": size, "from": frm, "query": {"bool": bool_q}, "sort": sort}


def _recipe_view(hit: dict) -> dict:
    s = hit.get("_source", {})
    deg = s.get("roastDegree")
    return {
        "uid": hit.get("_id"),
        "name": s.get("name"),
        "country": s.get("country") or None,
        "process": s.get("process") or None,
        "roastDegree": deg,
        "roastLevel": ROAST_DEGREE_LABELS.get(deg) if isinstance(deg, int) else None,
        "weight": s.get("weight"),
        "downloadCount": s.get("downloadCount") or 0,
        "deviceType": s.get("deviceType") or None,
        "userId": s.get("userId"),
        "userHandle": public_handle(s),
        "referenceRoastUid": s.get("referenceRoastUid"),
        "updatedAt": s.get("updatedAt"),
        "url": recipe_public_url(s, hit.get("_id")),
    }


def search(params: dict) -> dict:
    body = {"modelType": MODEL_RECIPE, "operation": "_search", "body": _build_query(params)}
    resp = _post(body)
    hits = resp.get("hits", {})
    total = hits.get("total", {})
    total_val = total.get("value") if isinstance(total, dict) else total
    return {
        "results": [_recipe_view(h) for h in hits.get("hits", [])],
        "total": total_val or 0,
        "relation": total.get("relation") if isinstance(total, dict) else "eq",
    }


def recipe_detail(uid: str) -> dict | None:
    body = {"modelType": MODEL_RECIPE, "operation": "_search",
            "body": {"size": 1, "query": {"term": {"_id": uid}}}}
    resp = _post(body)
    hits = resp.get("hits", {}).get("hits", [])
    return _recipe_view(hits[0]) if hits else None


# --------------------------------------------------------------------------- #
# Facetas (agregaciones) — cacheadas; se piden de una en una (el proxy hace
# timeout si se combinan varias aggs con query pesada).
# --------------------------------------------------------------------------- #
_FACET_CACHE: dict = {"at": 0.0, "data": None}
_FACET_TTL = 600  # 10 min


def _agg(field: str, size: int = 20) -> list[tuple]:
    body = {"modelType": MODEL_RECIPE, "operation": "_search",
            "body": {"size": 0, "aggs": {"f": {"terms": {"field": field, "size": size}}}}}
    try:
        resp = _post(body, timeout=20)
        buckets = resp.get("aggregations", {}).get("f", {}).get("buckets", [])
        return [(b["key"], b["doc_count"]) for b in buckets if b.get("key") not in ("", None)]
    except CommunityError:
        return []


def facets(force: bool = False) -> dict:
    now = time.time()
    if not force and _FACET_CACHE["data"] and now - _FACET_CACHE["at"] < _FACET_TTL:
        return _FACET_CACHE["data"]
    countries = [k for k, _ in _agg("country.keyword", 25)]
    processes = [k for k, _ in _agg("process.keyword", 25)]
    degrees = sorted({k for k, _ in _agg("roastDegree", 10) if isinstance(k, int)})
    levels = [ROAST_DEGREE_LABELS[d] for d in degrees if d in ROAST_DEGREE_LABELS]
    data = {
        "country": countries,
        "process": processes,
        "level": levels,
        "device": [k for k, _ in _agg("deviceType", 15)],
    }
    _FACET_CACHE.update(at=now, data=data)
    return data


# --------------------------------------------------------------------------- #
# Perfil de tueste (Power 1-9 + curva real de temperatura) — comparativa (FASE 2.5)
#
# El log COMPLETO del tueste (curvas + acciones de Power/Fan/Drum) está en Firebase
# Storage, en una URL PÚBLICA (sin auth). El campo `url` de ese log lo da el índice
# de roasts (proxy modelType 1) filtrando por recipeID. Flujo:
#   recipe.uid --(proxy mt=1)--> roast.url (storage) --(GET público)--> log completo.
# --------------------------------------------------------------------------- #
# ctrlType dentro de actions.actionTimeList del log de Storage (derivado de datos).
CTRL_LABELS = {0: "power", 1: "fan", 2: "drum"}


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _roast_url_for_recipe(recipe_uid: str, reference_roast_uid: str | None) -> tuple[str | None, dict]:
    """Devuelve (url_storage, _source) del log de tueste asociado a la receta."""
    should = [{"term": {"recipeID.keyword": recipe_uid}}]
    if reference_roast_uid:
        should.append({"term": {"_id": reference_roast_uid}})
    body = {"modelType": 1, "operation": "_search",
            "body": {"size": 5, "query": {"bool": {"should": should, "minimum_should_match": 1}}}}
    hits = _post(body).get("hits", {}).get("hits", [])
    # preferir el roast cuyo recipeID coincide con la receta
    best = next((h for h in hits if h.get("_source", {}).get("recipeID") == recipe_uid), None)
    best = best or (hits[0] if hits else None)
    if not best:
        return None, {}
    return best["_source"].get("url"), best["_source"]


def _fetch_storage(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise CommunityError(f"HTTP {exc.code} al descargar el log de tueste")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise CommunityError(f"no se pudo leer el log de tueste: {exc}")


def _downsample(curve: list, sample_rate: float, step_s: float = 5.0) -> list:
    """Reduce una curva (1 punto/sample) a ~1 punto cada step_s segundos: [[t,valor],...]."""
    if not curve or not sample_rate:
        return []
    stride = max(1, int(round(step_s * sample_rate)))
    out = []
    for i in range(0, len(curve), stride):
        v = curve[i]
        if isinstance(v, (int, float)):
            out.append([round(i / sample_rate, 1), round(v, 2)])
    return out


def build_profile_from_log(recipe_meta: dict, log: dict) -> dict:
    """Construye el perfil comparable a partir del log de Storage."""
    sr = log.get("sampleRate") or 1
    series = {name: [] for name in ("power", "fan", "drum")}
    for a in log.get("actions", {}).get("actionTimeList", []):
        label = CTRL_LABELS.get(a.get("ctrlType"))
        idx = _to_int(a.get("index"))
        val = _to_int(a.get("value"))
        if label and idx is not None and val is not None:
            series[label].append([round(idx / sr, 1), val])
    for s in series.values():
        s.sort(key=lambda p: p[0])

    def ms_time(idx):
        return round(idx / sr, 1) if isinstance(idx, int) and idx > 0 else None

    return {
        "uid": recipe_meta.get("uid"),
        "name": recipe_meta.get("name") or log.get("roastName"),
        "country": recipe_meta.get("country") or None,
        "process": recipe_meta.get("process") or None,
        "roastDegree": log.get("roastDegree"),
        "roastLevel": ROAST_DEGREE_LABELS.get(log.get("roastDegree")),
        "weight": recipe_meta.get("weight"),
        "totalRoastTime": log.get("totalRoastTime"),
        "sampleRate": sr,
        "series": series,                                   # power/fan/drum: [[seg, valor1-9]]
        "beanTemp": _downsample(log.get("beanTemperature", []), sr),  # curva real [[seg,°C]]
        "milestones": {
            "yellowing": ms_time(log.get("indexYellowingStart")),
            "firstCrackStart": ms_time(log.get("indexFirstCrackStart")),
            "firstCrackEnd": ms_time(log.get("indexFirstCrackEnd")),
        },
        "duration": log.get("totalRoastTime") or (len(log.get("beanTemperature", [])) / sr if sr else 0),
        "url": recipe_meta.get("url"),  # /{handle}/recipes/{id}, ya resuelto en recipe_detail
    }


def _cache_get(uid: str) -> dict | None:
    try:
        conn = sqlite3.connect(PROFILE_DB)
        conn.execute("CREATE TABLE IF NOT EXISTS recipe_profiles "
                     "(uid TEXT PRIMARY KEY, fetchedAt INTEGER, data TEXT)")
        row = conn.execute("SELECT fetchedAt, data FROM recipe_profiles WHERE uid=?", (uid,)).fetchone()
        conn.close()
        if row and time.time() - row[0] < PROFILE_TTL:
            return json.loads(row[1])
    except sqlite3.Error:
        pass
    return None


def _cache_put(uid: str, data: dict) -> None:
    try:
        conn = sqlite3.connect(PROFILE_DB)
        conn.execute("CREATE TABLE IF NOT EXISTS recipe_profiles "
                     "(uid TEXT PRIMARY KEY, fetchedAt INTEGER, data TEXT)")
        conn.execute("INSERT OR REPLACE INTO recipe_profiles VALUES (?,?,?)",
                     (uid, int(time.time()), json.dumps(data, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except sqlite3.Error:
        pass


def recipe_profile(uid: str, reference_roast_uid: str | None = None, use_cache: bool = True) -> dict:
    if use_cache:
        cached = _cache_get(uid)
        if cached:
            return cached
    # 1) localizar la receta (metadatos) si no nos pasaron el referenceRoastUid
    meta = {"uid": uid}
    if reference_roast_uid is None:
        rd = recipe_detail(uid)
        if rd:
            meta = rd
            reference_roast_uid = rd.get("referenceRoastUid")
    # 2) obtener la URL del log de tueste (Storage) vía el índice de roasts
    storage_url, roast_src = _roast_url_for_recipe(uid, reference_roast_uid)
    if not storage_url:
        raise CommunityError(f"la receta {uid} no tiene un log de tueste asociado para comparar")
    # 3) descargar el log público y construir el perfil
    log = _fetch_storage(storage_url)
    profile = build_profile_from_log(meta, log)
    _cache_put(uid, profile)
    return profile


def compare(uids: list[str]) -> dict:
    """Descarga (con caché) los perfiles de varias recetas para superponerlos."""
    profiles, errors = [], []
    for uid in uids:
        try:
            profiles.append(recipe_profile(uid))
        except CommunityError as exc:
            errors.append({"uid": uid, "error": str(exc)})
    return {"profiles": profiles, "errors": errors}
