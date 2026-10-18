# CLAUDE.md — notas de trabajo del proyecto

Contexto para sesiones de Claude Code. El README cubre el uso; aquí van las decisiones
de diseño y los hilos abiertos. Idioma del proyecto: español.

## Convenciones

- Solo librería estándar de Python; web en vanilla JS + SVG, sin dependencias.
- `web/index.html` (servidor local, `serve.py`) y `docs/index.html` (GitHub Pages,
  estático) comparten la lógica de comparativa **duplicada**. Cualquier cambio en la
  comparativa se aplica a los dos archivos.
- Trabajo en `main` con merge automático desde la rama de sesión (preferencia del usuario).
- Nunca commitear `.env`, `catalog.db` ni tokens.

## Decisiones de diseño

### Receta central (2026-10-18)
- Pregunta del usuario: de varias curvas seleccionadas, elegir una para tostar que sea
  «la media, más o menos, la que está por el centro».
- Alternativas valoradas: media recortada 20/20 punto a punto (idea original), mediana
  punto a punto + más cercana, **medoide** (elegida: un paso, sin parámetros, siempre
  devuelve una receta real, y además ordena todas de más central a más rara).
- Eje de tiempo **normalizado al 100 % del tueste**, no alineado al 1er crack: la
  diferencia de duración entre recetas se debe sobre todo al peso del lote.
- Power pesa 70 %, temperatura de grano 30 % (constantes `W_POWER`, `W_TEMP`).
- Atípicas: distancia a la central > 1,5× la mediana (mínimo 0,02 normalizado), solo
  con 4 o más recetas.
- Pendiente de verificar con token: si el objeto receta (proxy `modelType` 2) incluye las
  acciones disparadas por temperatura de grano (en RoasTime una receta puede disparar
  por tiempo o por temperatura). El log de Storage da las acciones por índice de tiempo
  y la curva `beanTemperature`, así que Power en función de la temperatura de grano se
  puede derivar cruzando ambas.

### Trazabilidad tueste → receta (2026-10-17)
- El índice de tuestes (proxy `modelType` 1) tiene `recipeID`; la API pública
  (`x-api-key`) no lo expone, y RoasTime/roast.world no lo muestran en la ficha.
- Idea pendiente: `roast_index.py` podría añadir `recipeID` a `catalog.db` consultando el
  proxy con `ROAST_FIREBASE_TOKEN`, y una vista «Mis tuestes» con la receta usada.

### Interfaz propia para el Bullet (aparcado, 2026-10-17)
- Viable: Artisan (`src/artisanlib/aillio_r1.py`) controla el R1 V2 por USB (PyUSB +
  libusb; VID 0x0483, PID 0x5741/0xa27e): power 0–9, fan 1–12, drum 1–9, PRS.
- Usuario: Bullet R1 V2, Windows. En Windows hace falta driver libusb (Zadig) que
  excluye al de RoasTime; USB exclusivo. Sin RoasTime se pierden firmware y subida
  automática a roast.world.
- Primer paso acordado si se retoma: script de solo lectura (temperaturas y estado).

## Verificación

- Sintaxis JS: extraer el `<script>` y `node --check`.
- Prueba e2e: servir `docs/` con un HTTP estático, interceptar
  `firebasestorage.googleapis.com` con logs sintéticos y recorrer comparar → elegir la
  central → quitar atípica (Playwright, Chromium preinstalado).
