#!/usr/bin/env python3
"""Indexador de tuestes de la Aillio Public API (roast.world) -> catalog.db.

FASE 1. Esquema verificado en SCHEMA.md.

Uso:
    export ROAST_API_TOKEN=...        # o ponlo en .env
    python roast_index.py             # lista de roasts + beans -> catalog.db
    python roast_index.py --detail    # ademas trae curvas/hitos de cada roast
    python roast_index.py --stats     # resumen de lo indexado

La autenticacion va en el header  x-api-key  (NO 'api-token'; ver SCHEMA.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.roast.world/api/v3/public"
DEFAULT_DB = "catalog.db"
PAGE_SIZE = 100  # maximo permitido por la API
# Cloudflare (error 1010) bloquea el User-Agent por defecto de urllib; usamos uno de navegador.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# Token / .env
# --------------------------------------------------------------------------- #
def load_env(path: str = ".env") -> None:
    """Carga variables de un .env sencillo en os.environ (sin pisar las ya puestas)."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def get_token() -> str:
    token = os.environ.get("ROAST_API_TOKEN", "").strip()
    if not token:
        sys.exit("ERROR: falta ROAST_API_TOKEN (ponlo en .env o exportalo).")
    return token


# --------------------------------------------------------------------------- #
# Cliente HTTP
# --------------------------------------------------------------------------- #
class ApiError(RuntimeError):
    pass


def api_get(path: str, token: str, params: dict | None = None, retries: int = 3) -> dict:
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"x-api-key": token, "Accept": "application/json", "User-Agent": USER_AGENT},
    )
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            if exc.code == 401:
                raise ApiError(f"401 no autorizado: {body}. Revisa ROAST_API_TOKEN y el header x-api-key.")
            if exc.code == 429 or 500 <= exc.code < 600:
                last_err = ApiError(f"HTTP {exc.code}: {body}")
                time.sleep(min(2 ** attempt, 10))
                continue
            raise ApiError(f"HTTP {exc.code}: {body}")
        except urllib.error.URLError as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 10))
    raise ApiError(f"fallo tras {retries} intentos: {last_err}")


def paginate(path: str, token: str) -> list[dict]:
    """Recorre todas las paginas de un endpoint envuelto {page,total,totalPages,data}."""
    out: list[dict] = []
    page = 1
    while True:
        payload = api_get(path, token, {"page": page, "size": PAGE_SIZE})
        data = payload.get("data", []) or []
        out.extend(data)
        total_pages = payload.get("totalPages", 1) or 1
        print(f"  {path}: pagina {page}/{total_pages} (+{len(data)}, acum {len(out)})")
        if page >= total_pages:
            break
        page += 1
    return out


# --------------------------------------------------------------------------- #
# Base de datos
# --------------------------------------------------------------------------- #
def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS roasts (
            uid                TEXT PRIMARY KEY,
            roastName          TEXT,
            dateTime           INTEGER,
            updatedAt          INTEGER,
            weightGreen        INTEGER,
            weightRoasted      INTEGER,
            totalRoastTime     INTEGER,
            preheatTemperature REAL,
            colorMeterScale    TEXT,
            beanId             TEXT,
            firstCrackTime     REAL,
            firstCrackTemp     REAL,
            firstCrackIRTemp   REAL,
            serialNumber       INTEGER,
            deviceType         TEXT,
            raw                TEXT      -- JSON original por si aparecen campos nuevos
        );

        CREATE TABLE IF NOT EXISTS beans (
            beanId    TEXT PRIMARY KEY,
            name      TEXT,
            country   TEXT,
            process   TEXT,
            farm      TEXT,
            inStock   INTEGER,
            varieties TEXT,   -- JSON array
            tags      TEXT,   -- JSON array
            createdAt TEXT,
            raw       TEXT
        );

        CREATE TABLE IF NOT EXISTS roast_detail (
            uid                   TEXT PRIMARY KEY REFERENCES roasts(uid),
            fetchedAt             INTEGER,
            indexYellowingStart   INTEGER,
            indexFirstCrackStart  INTEGER,
            indexFirstCrackEnd    INTEGER,
            indexSecondCrackStart INTEGER,
            indexSecondCrackEnd   INTEGER,
            curves                TEXT,   -- JSON: beanTemperature, ibtsTemperature, derivadas...
            actions               TEXT,   -- JSON array de eventos
            raw                   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_roasts_beanId ON roasts(beanId);
        CREATE INDEX IF NOT EXISTS idx_roasts_dateTime ON roasts(dateTime);
        """
    )
    return conn


def upsert_roasts(conn: sqlite3.Connection, rows: list[dict]) -> None:
    cols = ["uid", "roastName", "dateTime", "updatedAt", "weightGreen", "weightRoasted",
            "totalRoastTime", "preheatTemperature", "colorMeterScale", "beanId",
            "firstCrackTime", "firstCrackTemp", "firstCrackIRTemp", "serialNumber", "deviceType"]
    conn.executemany(
        f"INSERT OR REPLACE INTO roasts ({','.join(cols)},raw) "
        f"VALUES ({','.join('?' * len(cols))},?)",
        [tuple(r.get(c) for c in cols) + (json.dumps(r, ensure_ascii=False),) for r in rows],
    )
    conn.commit()


def upsert_beans(conn: sqlite3.Connection, rows: list[dict]) -> None:
    def row(b: dict) -> tuple:
        return (
            b.get("beanId"), b.get("name"), b.get("country"), b.get("process"),
            b.get("farm"), b.get("inStock"),
            json.dumps(b.get("varieties", []), ensure_ascii=False),
            json.dumps(b.get("tags", []), ensure_ascii=False),
            b.get("createdAt"), json.dumps(b, ensure_ascii=False),
        )
    conn.executemany(
        "INSERT OR REPLACE INTO beans "
        "(beanId,name,country,process,farm,inStock,varieties,tags,createdAt,raw) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        [row(b) for b in rows],
    )
    conn.commit()


def upsert_detail(conn: sqlite3.Connection, uid: str, d: dict) -> None:
    curve_keys = ["beanTemperature", "ibtsTemperature", "beanDerivative", "ibtsDerivative",
                  "differentialAirPressure", "exhaustFanBlowerRpm"]
    curves = {k: d.get(k) for k in curve_keys}
    conn.execute(
        "INSERT OR REPLACE INTO roast_detail "
        "(uid,fetchedAt,indexYellowingStart,indexFirstCrackStart,indexFirstCrackEnd,"
        "indexSecondCrackStart,indexSecondCrackEnd,curves,actions,raw) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            uid, int(time.time()),
            d.get("indexYellowingStart"), d.get("indexFirstCrackStart"),
            d.get("indexFirstCrackEnd"), d.get("indexSecondCrackStart"),
            d.get("indexSecondCrackEnd"),
            json.dumps(curves, ensure_ascii=False),
            json.dumps(d.get("actions", []), ensure_ascii=False),
            json.dumps(d, ensure_ascii=False),
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------- #
# Comandos
# --------------------------------------------------------------------------- #
def cmd_index(args: argparse.Namespace) -> None:
    token = get_token()
    conn = connect(args.db)

    print("Indexando roasts...")
    roasts = paginate("/roasts", token)
    upsert_roasts(conn, roasts)
    print(f"  -> {len(roasts)} roasts guardados")

    print("Indexando beans...")
    beans = paginate("/beans", token)
    upsert_beans(conn, beans)
    print(f"  -> {len(beans)} beans guardados")

    if args.detail:
        print(f"Trayendo detalle de {len(roasts)} roasts (curvas/hitos)...")
        for i, r in enumerate(roasts, 1):
            uid = r["uid"]
            try:
                detail = api_get(f"/roasts/{uid}", token)
                upsert_detail(conn, uid, detail)
                print(f"  [{i}/{len(roasts)}] {uid} ok")
            except ApiError as exc:
                print(f"  [{i}/{len(roasts)}] {uid} FALLO: {exc}", file=sys.stderr)
            time.sleep(args.delay)

    conn.close()
    print(f"Hecho. Base de datos: {args.db}")
    cmd_stats(args)


def cmd_stats(args: argparse.Namespace) -> None:
    if not os.path.exists(args.db):
        print("(aun no hay catalog.db; ejecuta el indexador primero)")
        return
    conn = sqlite3.connect(args.db)
    n_roasts = conn.execute("SELECT COUNT(*) FROM roasts").fetchone()[0]
    n_beans = conn.execute("SELECT COUNT(*) FROM beans").fetchone()[0]
    n_detail = conn.execute(
        "SELECT COUNT(*) FROM roast_detail"
    ).fetchone()[0] if _table_exists(conn, "roast_detail") else 0
    print(f"\n== catalog.db ==\n  roasts:        {n_roasts}\n  beans:         {n_beans}\n  con detalle:   {n_detail}")
    conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def main() -> None:
    load_env()
    p = argparse.ArgumentParser(description="Indexador de tuestes roast.world -> SQLite")
    p.add_argument("--db", default=DEFAULT_DB, help=f"ruta de la BD (default: {DEFAULT_DB})")
    p.add_argument("--detail", action="store_true", help="traer curvas/hitos de cada roast")
    p.add_argument("--delay", type=float, default=0.2, help="pausa entre llamadas de detalle (s)")
    p.add_argument("--stats", action="store_true", help="solo mostrar resumen, sin indexar")
    args = p.parse_args()

    if args.stats:
        cmd_stats(args)
    else:
        cmd_index(args)


if __name__ == "__main__":
    main()
