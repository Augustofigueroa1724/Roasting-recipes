#!/usr/bin/env python3
"""Servidor de busqueda de recetas de tueste (FASE 2).

Sirve una interfaz HTML de una pagina + API JSON sobre catalog.db.
Sin dependencias externas (solo stdlib).

    python serve.py            # http://localhost:8000
    python serve.py --port 9000 --db catalog.db

Endpoints:
    GET /                  -> web/index.html
    GET /api/facets        -> valores disponibles para los criterios cerrados
    GET /api/search?...    -> resultados filtrados (q, country, variety, process, level, device)
    GET /api/roast/<uid>   -> detalle de un tueste (hitos + resumen de curvas)
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import community
from enrich import enrich_roast

DB_PATH = "catalog.db"
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")


# --------------------------------------------------------------------------- #
# Acceso a datos
# --------------------------------------------------------------------------- #
def load_roasts() -> list[dict]:
    """Carga roasts + datos del bean asociado (si existe) y los enriquece."""
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = []
    for r in conn.execute("SELECT * FROM roasts"):
        d = dict(r)
        if d.get("beanId"):
            bean = conn.execute(
                "SELECT country, process, varieties FROM beans WHERE beanId=?", (d["beanId"],)
            ).fetchone()
            if bean:
                d["_beanCountry"] = bean["country"]
                d["_beanProcess"] = bean["process"]
                try:
                    d["_beanVarieties"] = json.loads(bean["varieties"] or "[]")
                except (TypeError, ValueError):
                    d["_beanVarieties"] = []
        rows.append(enrich_roast(d))
    conn.close()
    return rows


def public_view(r: dict) -> dict:
    """Subconjunto de campos que expone la API (sin 'raw' ni curvas pesadas)."""
    keys = ["uid", "roastName", "country", "varieties", "process", "roastLevel",
            "developmentRatio", "weightLoss", "weightGreen", "weightRoasted",
            "totalRoastTime", "firstCrackTime", "firstCrackTemp", "preheatTemperature",
            "deviceType", "serialNumber", "dateTime"]
    return {k: r.get(k) for k in keys}


def build_facets(roasts: list[dict]) -> dict:
    def distinct(key):
        vals = set()
        for r in roasts:
            v = r.get(key)
            if isinstance(v, list):
                vals.update(v)
            elif v not in (None, ""):
                vals.add(v)
        return sorted(vals, key=lambda x: str(x))
    return {
        "country": distinct("country"),
        "variety": distinct("varieties"),
        "process": distinct("process"),
        "level": distinct("roastLevel"),
        "device": distinct("deviceType"),
        "total": len(roasts),
    }


def search(roasts: list[dict], params: dict) -> list[dict]:
    def get(k):
        v = params.get(k, [""])
        return v[0].strip() if v else ""

    q = get("q").lower()
    country = get("country")
    variety = get("variety")
    process = get("process")
    level = get("level")
    device = get("device")

    out = []
    for r in roasts:
        if q and q not in (r.get("roastName") or "").lower():
            continue
        if country and r.get("country") != country:
            continue
        if variety and variety not in (r.get("varieties") or []):
            continue
        if process and r.get("process") != process:
            continue
        if level and r.get("roastLevel") != level:
            continue
        if device and r.get("deviceType") != device:
            continue
        out.append(public_view(r))
    out.sort(key=lambda r: r.get("dateTime") or 0, reverse=True)
    return out


def roast_detail(uid: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    base = conn.execute("SELECT * FROM roasts WHERE uid=?", (uid,)).fetchone()
    if not base:
        conn.close()
        return None
    out = enrich_roast(dict(base))
    out = public_view(out)
    det = conn.execute("SELECT * FROM roast_detail WHERE uid=?", (uid,)).fetchone()
    if det:
        d = dict(det)
        out["milestones"] = {
            k: d.get(k) for k in
            ["indexYellowingStart", "indexFirstCrackStart", "indexFirstCrackEnd",
             "indexSecondCrackStart", "indexSecondCrackEnd"]
        }
        try:
            curves = json.loads(d.get("curves") or "{}")
            out["curveLengths"] = {k: (len(v) if isinstance(v, list) else 0) for k, v in curves.items()}
            out["actions"] = json.loads(d.get("actions") or "[]")
            out["hasDetail"] = True
        except (TypeError, ValueError):
            out["hasDetail"] = True
    else:
        out["hasDetail"] = False
    conn.close()
    return out


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, content_type):
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except FileNotFoundError:
            self._json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        params = parse_qs(parsed.query)

        def flat(d):  # parse_qs -> dict de strings simples
            return {k: (v[0] if v else "") for k, v in d.items()}

        try:
            if route == "/" or route == "/index.html":
                self._file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
            elif route == "/api/facets":
                self._json(community.facets())
            elif route == "/api/search":
                self._json(community.search(flat(params)))
            elif route.startswith("/api/roast/"):
                uid = route[len("/api/roast/"):]
                detail = community.recipe_detail(uid)
                self._json(detail if detail else {"error": "not found"}, 200 if detail else 404)
            elif route.startswith("/api/profile/"):
                uid = route[len("/api/profile/"):]
                self._json(community.recipe_profile(uid))
            elif route == "/api/compare":
                uids = [u for u in (flat(params).get("uids", "").split(",")) if u]
                self._json(community.compare(uids))
            elif route == "/api/local/search":  # acceso al catálogo propio (los 4 roasts)
                self._json({"results": search(load_roasts(), params)})
            else:
                self._json({"error": "not found"}, 404)
        except community.CommunityError as exc:
            self._json({"error": str(exc)}, 502)

    def log_message(self, fmt, *args):  # silenciar logs ruidosos
        return


def main():
    global DB_PATH
    from roast_index import load_env
    load_env()
    p = argparse.ArgumentParser(description="Servidor de busqueda de recetas (FASE 2)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--db", default=DB_PATH)
    args = p.parse_args()
    DB_PATH = args.db

    if not os.environ.get("ROAST_FIREBASE_TOKEN"):
        print("AVISO: falta ROAST_FIREBASE_TOKEN en .env -> la búsqueda de comunidad fallará.")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"Buscador (catálogo de COMUNIDAD) en  http://localhost:{args.port}")
    print("Ctrl+C para parar.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nParado.")


if __name__ == "__main__":
    main()
