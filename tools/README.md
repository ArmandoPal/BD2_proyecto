# Utilidades de validación

Los comandos se ejecutan desde la raíz del repositorio usando el Python del entorno virtual.

- `python tools/inspect_page.py ARCHIVO --page 1 --page-size 4096`: lee una página y su metadata real. No altera el archivo.
- `python tools/validate_products.py --data-dir data/nueva_validacion`: importa y compara 1000, 10000, 100000 y 500000 filas tras reabrir. Requiere un directorio sin tablas previas.
- `python tools/validate_large_indexes.py --data-dir data/validation/500000 --n 500000`: construye/reabre índices, recorre todo el B+ y comprueba 1002 búsquedas por índice.
- `python tools/build_report.py`: genera tablas desde los cuatro experimentos completos y compila `informe/main.pdf`. Acepta `--compiler RUTA`.

## Comprobación opcional del navegador

No se necesita Node ni Playwright para ejecutar el cliente; solo para automatizar esta comprobación. Con Node y npm instalados:

```powershell
npm install --no-save --package-lock=false playwright
npx playwright install chromium
node tools/check_frontend.cjs
```

El servidor debe estar activo en `http://127.0.0.1:8000`, con una tabla `products` de al menos 200 filas (la base local preparada contiene 500000). `BD2_URL` permite elegir otro origen. `PLAYWRIGHT_MODULE` permite usar una instalación existente de Playwright y `CHROME_PATH` un ejecutable de Chrome existente.

El script prueba resultados reales, paginación, separación entre SQL editado y SQL ejecutado, métricas tras errores, tres tamaños de pantalla y ausencia de errores JavaScript. Guarda capturas y un JSON en `output/qa/`. Estos archivos de inspección local no se versionan; el resumen de la validación final se conserva también en `benchmarks/results/frontend_validation.json`.
