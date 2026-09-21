"""Ejecuta experimentos de forma secuencial para evitar interferencia entre ellos."""

import argparse
import subprocess
import sys

MODULES = {
    1: "exp1_insercion_masiva",
    2: "exp2_busqueda_puntual",
    3: "exp3_busqueda_rango",
    4: "exp4_sensibilidad_bloque",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--experiments",
        type=int,
        nargs="+",
        choices=list(MODULES),
        default=list(MODULES),
    )
    parser.add_argument("--csv")
    args = parser.parse_args()
    for number in args.experiments:
        command = [sys.executable, "-m", "benchmarks." + MODULES[number]]
        if args.csv:
            command.extend(["--csv", args.csv])
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
