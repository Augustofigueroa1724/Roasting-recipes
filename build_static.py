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


META_FIELDS = ["name", "country", "process", "roastDegree", "weight", "downloadCount", "deviceType"]


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
    p.add_argument("--meta-limit", type=int, default=5000, help="recetas en el índice de búsqueda (metadatos)")
    p.add_argument("--profile-limit", type=int, default=250, help="recetas con perfil descargado (para comparar)")
    p.add_argument("--delay", type=float, default=0.15, help="pausa entre perfiles (s)")
    p.add_argument("--stamp", default="", help="fecha del snapshot (ISO); si vacío, sin fecha")
    args = p.parse_args()

    os.makedirs(PROFILES, exist_ok=True)

    print(f"1) Descargando metadatos de hasta {args.meta_limit} recetas (orden por popularidad)…")
    recipes = fetch_all_recipes(args.meta_limit)
    print(f"   -> {len(recipes)} recetas para el índice de búsqueda")

    n_prof = min(args.profile_limit, len(recipes))
    print(f"2) Descargando perfiles (Power/temperatura) de las {n_prof} más populares…")
    with_profile = 0
    kept: list[dict] = []
    for i, r in enumerate(recipes, 1):
        if i > n_prof:
            r["hasProfile"] = False
            kept.append(r)
            continue
        uid = r["uid"]
        try:
            prof = community.recipe_profile(uid)
            # tomar el grado de tueste del log (más fiable) si falta en el metadato
            if r.get("roastDegree") in (None, "") and prof.get("roastDegree") is not None:
                r["roastDegree"] = prof.get("roastDegree")
            with open(os.path.join(PROFILES, f"{uid}.json"), "w", encoding="utf-8") as fh:
                json.dump(prof, fh, ensure_ascii=False)
            r["hasProfile"] = True
            with_profile += 1
        except community.CommunityError as exc:
            r["hasProfile"] = False
            print(f"   [{i}/{len(recipes)}] {uid} sin perfil: {str(exc)[:50]}")
        kept.append(r)
        if i % 25 == 0:
            print(f"   …{i}/{n_prof} ({with_profile} con perfil)")
        time.sleep(args.delay)

    print("3) Escribiendo JSON estáticos…")
    # formato COLUMNAR (sin repetir claves) para que el índice de ~97k pese poco.
    # uid + metadatos + hasProfile; el frontend deriva roastLevel y la url.
    fields = ["uid"] + META_FIELDS + ["hasProfile"]
    rows = [[r.get(f) for f in fields] for r in kept]
    with open(os.path.join(DATA, "recipes.json"), "w", encoding="utf-8") as fh:
        json.dump({"fields": fields, "rows": rows}, fh, ensure_ascii=False)
    with open(os.path.join(DATA, "facets.json"), "w", encoding="utf-8") as fh:
        json.dump(build_facets(kept), fh, ensure_ascii=False)
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"count": len(kept), "withProfile": with_profile,
                   "generatedAt": args.stamp, "source": "roast.world community"}, fh, ensure_ascii=False)

    print(f"Hecho. {len(kept)} recetas en el índice, {with_profile} con perfil -> {DATA}")


if __name__ == "__main__":
    main()
