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
import time
import urllib.error
import urllib.request

PROXY_URL = "https://api.roast.world/api/v3/proxy"
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
        "referenceRoastUid": s.get("referenceRoastUid"),
        "updatedAt": s.get("updatedAt"),
        "url": f"https://roast.world/recipes/{hit.get('_id')}",
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
