#!/usr/bin/env python3
"""Genera un snapshot ESTÁTICO del catálogo para publicar en GitHub Pages.

Usa tu ROAST_FIREBASE_TOKEN (en .env) en tiempo de BUILD para descargar un
subconjunto de recetas populares + sus perfiles, y los escribe como JSON en
docs/. La web pública (docs/index.html) lee solo esos archivos: NO usa tu token
en producción ni llama a roast.world desde el navegador del visitante.

    python3 build_static.py            # top 150 recetas por descargas
    python3 build_static.py --limit 80 # menos (build más rápido)

Salida:
    docs/data/recipes.json        lista de metadatos (para buscar/filtrar en cliente)
    docs/data/facets.json         valores de los filtros (derivados del snapshot)
    docs/data/profiles/<uid>.json perfil de cada receta (para la comparativa)
    docs/data/meta.json           info del snapshot (fecha, recuento)
"""
from __future__ import annotations

import argparse
import json
import os
import time

import community
from roast_index import load_env

DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs")
DATA = os.path.join(DOCS, "data")
PROFILES = os.path.join(DATA, "profiles")


META_FIELDS = ["name", "country", "process", "roastDegree", "weight", "downloadCount", "deviceType", "referenceRoastUid"]


def fetch_all_recipes(max_n: int) -> list[dict]:
    """Todas las recetas públicas (metadatos) por downloadCount desc, vía search_after.

    El `from/size` de Elasticsearch corta en 10.000, así que paginamos con
    search_after sobre el sort [downloadCount desc, updatedAt asc].
    """
    out: list[dict] = []
    seen: set[str] = set()
    after = None
    page = 1000
    while len(out) < max_n:
        body = {
            "size": page,
            "_source": META_FIELDS,
            "query": {"bool": {"must_not": [{"term": {"deleted": 1}}, {"term": {"isPrivate": 1}}]}},
            "sort": [{"downloadCount": "desc"}, {"updatedAt": "asc"}],
        }
        if after is not None:
            body["search_after"] = after
        resp = community._post({"modelType": 2, "operation": "_search", "body": body}, timeout=40)
        hits = resp.get("hits", {}).get("hits", [])
        if not hits:
            break
        for h in hits:
            uid = h["_id"]
            if uid in seen:
                continue
            seen.add(uid)
            s = h.get("_source", {})
            row = {"uid": uid}
            for f in META_FIELDS:
                row[f] = s.get(f)
            out.append(row)
        after = hits[-1].get("sort")
        print(f"  metadatos: {len(out)}")
        time.sleep(0.05)
        if len(hits) < page:
            break
    return out[:max_n]


def build_facets(recipes: list[dict]) -> dict:
    from collections import Counter
    def top(key, n):
        c = Counter(r.get(key) for r in recipes if r.get(key) not in (None, ""))
        return [k for k, _ in c.most_common(n)]
    degrees = sorted({r.get("roastDegree") for r in recipes if isinstance(r.get("roastDegree"), int)})
    return {
        "country": top("country", 40),
        "process": top("process", 25),
        "level": [community.ROAST_DEGREE_LABELS[d] for d in degrees if d in community.ROAST_DEGREE_LABELS],
        "device": top("deviceType", 15),
    }


def main():
    load_env()
    p = argparse.ArgumentParser(description="Genera el snapshot estático para GitHub Pages")
    p.add_argument("--meta-limit", type=int, default=100000, help="máx. recetas en el índice de búsqueda")
    p.add_argument("--stamp", default="", help="fecha del snapshot (ISO); si vacío, sin fecha")
    args = p.parse_args()

    os.makedirs(DATA, exist_ok=True)

    print(f"1) Descargando metadatos de hasta {args.meta_limit} recetas (orden por popularidad)…")
    recipes = fetch_all_recipes(args.meta_limit)
    print(f"   -> {len(recipes)} recetas para el índice de búsqueda")

    print("2) Escribiendo JSON estáticos…")
    # formato COLUMNAR (sin repetir claves). 'ref' = referenceRoastUid: el navegador
    # baja el log de Firebase Storage (público, CORS *) al vuelo para comparar.
    # NO se pre-generan perfiles: el frontend los construye en cliente.
    out_fields = ["uid", "name", "country", "process", "roastDegree", "weight", "downloadCount", "deviceType", "ref"]
    def to_row(r):
        vals = [r.get(f) for f in out_fields[:-1]]
        vals.append(r.get("referenceRoastUid"))
        return vals
    comparable = sum(1 for r in recipes if r.get("referenceRoastUid"))
    rows = [to_row(r) for r in recipes]
    with open(os.path.join(DATA, "recipes.json"), "w", encoding="utf-8") as fh:
        json.dump({"fields": out_fields, "rows": rows}, fh, ensure_ascii=False)
    with open(os.path.join(DATA, "facets.json"), "w", encoding="utf-8") as fh:
        json.dump(build_facets(recipes), fh, ensure_ascii=False)
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"count": len(recipes), "comparable": comparable,
                   "generatedAt": args.stamp, "source": "roast.world community"}, fh, ensure_ascii=False)

    print(f"Hecho. {len(recipes)} recetas en el índice, {comparable} comparables (con ref) -> {DATA}")


if __name__ == "__main__":
    main()
