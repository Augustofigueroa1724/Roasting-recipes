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


def fetch_top_recipes(limit: int) -> list[dict]:
    """Top recetas por downloadCount (paginando el catálogo de comunidad)."""
    out: list[dict] = []
    page_size = 100
    frm = 0
    while len(out) < limit:
        res = community.search({"size": page_size, "from": frm, "sortBy": "popularity"})
        rows = res.get("results", [])
        if not rows:
            break
        out.extend(rows)
        frm += page_size
        print(f"  metadatos: {len(out)} (total catálogo ~{res.get('total')})")
        if frm >= (res.get("total") or 0):
            break
    return out[:limit]


def build_facets(recipes: list[dict]) -> dict:
    def distinct(key):
        vals = {r.get(key) for r in recipes if r.get(key)}
        return sorted(vals, key=str)
    return {
        "country": distinct("country"),
        "process": distinct("process"),
        "level": distinct("roastLevel"),
        "device": distinct("deviceType"),
    }


def main():
    load_env()
    p = argparse.ArgumentParser(description="Genera el snapshot estático para GitHub Pages")
    p.add_argument("--limit", type=int, default=150, help="nº de recetas (default 150)")
    p.add_argument("--delay", type=float, default=0.15, help="pausa entre perfiles (s)")
    p.add_argument("--stamp", default="", help="fecha del snapshot (ISO); si vacío, sin fecha")
    args = p.parse_args()

    os.makedirs(PROFILES, exist_ok=True)

    print(f"1) Descargando metadatos de las {args.limit} recetas más populares…")
    recipes = fetch_top_recipes(args.limit)
    print(f"   -> {len(recipes)} recetas")

    print("2) Descargando perfiles (Power/temperatura) de cada receta…")
    with_profile = 0
    kept: list[dict] = []
    for i, r in enumerate(recipes, 1):
        uid = r["uid"]
        try:
            prof = community.recipe_profile(uid, reference_roast_uid=r.get("referenceRoastUid"))
            # tomar el grado de tueste del log (más fiable) si falta en el metadato
            if not r.get("roastLevel") and prof.get("roastLevel"):
                r["roastLevel"] = prof["roastLevel"]
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
            print(f"   …{i}/{len(recipes)} ({with_profile} con perfil)")
        time.sleep(args.delay)

    print("3) Escribiendo JSON estáticos…")
    # quitar campos internos del JSON público (no se exponen userId/referenceRoastUid)
    public = [{k: v for k, v in r.items() if k not in ("userId", "referenceRoastUid")} for r in kept]
    with open(os.path.join(DATA, "recipes.json"), "w", encoding="utf-8") as fh:
        json.dump(public, fh, ensure_ascii=False)
    with open(os.path.join(DATA, "facets.json"), "w", encoding="utf-8") as fh:
        json.dump(build_facets(kept), fh, ensure_ascii=False)
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump({"count": len(kept), "withProfile": with_profile,
                   "generatedAt": args.stamp, "source": "roast.world community"}, fh, ensure_ascii=False)

    print(f"Hecho. {len(kept)} recetas, {with_profile} con perfil -> {DATA}")


if __name__ == "__main__":
    main()
