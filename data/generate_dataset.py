"""
Genera/recorta el dataset de prueba a un volumen de 100,000-500,000 registros
(3.6 Conjuntos de Datos de Prueba).

Uso:
    python generate_dataset.py --n 100000

Guarda el resultado en data/processed/dataset.csv con una semilla fija
para reproducibilidad entre corridas de benchmarks.
"""

import argparse

SEED = 42


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100_000)
    parser.add_argument("--source", type=str, default="raw/dataset_original.csv")
    parser.add_argument("--output", type=str, default="processed/dataset.csv")
    args = parser.parse_args()

    # TODO: cargar data/raw/<dataset original>, muestrear/recortar a args.n filas
    # con semilla fija (SEED) y guardar en args.output con el esquema
    # (INT, CHAR(n), FLOAT) que usará CREATE TABLE.
    raise NotImplementedError


if __name__ == "__main__":
    main()
