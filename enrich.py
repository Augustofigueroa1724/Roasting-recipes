"""Enriquecimiento de datos de tueste: deriva criterios cerrados a partir de los
campos reales (nombre, beans, metricas). No inventa datos; lo derivado se marca
como estimado en la UI.  Compartido por el servidor de busqueda (FASE 2).
"""
from __future__ import annotations

# Origenes de cafe frecuentes. Clave = etiqueta canonica; valores = subcadenas a
# buscar en el nombre (incluye variantes/erratas vistas en datos reales).
COUNTRY_ALIASES: dict[str, list[str]] = {
    "Ethiopia": ["ethiopia", "etiopia", "yirgacheffe", "sidamo", "guji", "harrar"],
    "Brazil": ["brazil", "brasil", "barzil"],  # 'barzil' = errata real en el catalogo
    "Colombia": ["colombia"],
    "Kenya": ["kenya", "kenia"],
    "Guatemala": ["guatemala"],
    "Honduras": ["honduras"],
    "Costa Rica": ["costa rica"],
    "Rwanda": ["rwanda", "ruanda"],
    "Burundi": ["burundi"],
    "Peru": ["peru", "perú"],
    "Mexico": ["mexico", "méxico"],
    "El Salvador": ["el salvador", "salvador"],
    "Nicaragua": ["nicaragua"],
    "Panama": ["panama", "panamá"],
    "Indonesia": ["indonesia", "sumatra", "java", "sulawesi"],
    "Yemen": ["yemen"],
    "India": ["india", "monsooned"],
    "Tanzania": ["tanzania"],
    "Uganda": ["uganda"],
    "Bolivia": ["bolivia"],
    "Ecuador": ["ecuador"],
    "Vietnam": ["vietnam"],
}

# Variedades comunes (subcadena, case-insensitive).
VARIETIES = [
    "Bourbon", "Catuai", "Caturra", "Typica", "Gesha", "Geisha", "SL28", "SL34",
    "Heirloom", "Pacamara", "Mundo Novo", "Maragogipe", "Castillo", "Catimor",
    "Pacas", "Villa Sarchi", "Tabi", "Wush Wush", "Ethiosar",
]

# Procesos comunes.
PROCESSES = ["Washed", "Natural", "Honey", "Anaerobic", "Wet Hulled", "Carbonic", "Lavado", "Natural"]


def detect_country(name: str | None, bean_country: str | None = None) -> str | None:
    if bean_country:
        return bean_country.strip()
    if not name:
        return None
    low = name.lower()
    for canonical, aliases in COUNTRY_ALIASES.items():
        if any(a in low for a in aliases):
            return canonical
    return None


def detect_varieties(name: str | None, bean_varieties: list[str] | None = None) -> list[str]:
    if bean_varieties:
        return bean_varieties
    if not name:
        return []
    low = name.lower()
    return [v for v in VARIETIES if v.lower() in low]


def detect_process(name: str | None, bean_process: str | None = None) -> str | None:
    if bean_process:
        return bean_process.strip()
    if not name:
        return None
    low = name.lower()
    for p in PROCESSES:
        if p.lower() in low:
            return p
    return None


def development_ratio(total_time: float | None, first_crack_time: float | None) -> float | None:
    """DTR = (tiempo total - tiempo a 1C) / tiempo total, en %."""
    if not total_time or not first_crack_time:
        return None
    return round((total_time - first_crack_time) / total_time * 100, 1)


def weight_loss(green: float | None, roasted: float | None) -> float | None:
    if not green or not roasted:
        return None
    return round((1 - roasted / green) * 100, 1)


def roast_level_estimate(dtr: float | None) -> str | None:
    """Nivel de tueste ESTIMADO a partir del DTR (no es dato oficial; orientativo).

    Sin temperatura de drop ni color, el DTR es la mejor pista disponible.
    """
    if dtr is None:
        return None
    if dtr < 15:
        return "Claro (estimado)"
    if dtr <= 22:
        return "Medio (estimado)"
    return "Oscuro (estimado)"


def enrich_roast(r: dict) -> dict:
    """Anade campos derivados a una fila de roast (dict)."""
    name = r.get("roastName")
    dtr = development_ratio(r.get("totalRoastTime"), r.get("firstCrackTime"))
    return {
        **r,
        "country": detect_country(name, r.get("_beanCountry")),
        "varieties": detect_varieties(name, r.get("_beanVarieties")),
        "process": detect_process(name, r.get("_beanProcess")),
        "developmentRatio": dtr,
        "weightLoss": weight_loss(r.get("weightGreen"), r.get("weightRoasted")),
        "roastLevel": roast_level_estimate(dtr),
    }
