# Dataset original

El proyecto utiliza el archivo proporcionado `products-500000.csv` (500000 filas, 14 columnas, 90764217 bytes). Se puede colocar aquí sin modificarlo o proporcionar su ubicación con `--csv` al importador.

La inspección encontró claves `Index` ascendentes y únicas entre 1 y 500000. `data/products.py` documenta el mapeo y los tipos. No se atribuye una fuente pública que no haya sido facilitada con el archivo.

El CSV se excluye de Git por tamaño. La evidencia de las cargas y comparaciones persistidas se conserva en `benchmarks/results/import_validation.json`.
