"""Recorta el CSV original en streaming; no genera registros ficticios."""

import argparse
import csv
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.products import find_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=100000)
    parser.add_argument("--source")
    parser.add_argument("--output", default="data/processed/dataset.csv")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n debe ser positivo")
    source, output = find_csv(args.source), Path(args.output)
    if source.resolve() == output.resolve():
        parser.error("La salida no puede sobrescribir el dataset original")
    output.parent.mkdir(parents=True, exist_ok=True)
    with (
        source.open(encoding="utf-8-sig", newline="") as inp,
        output.open("w", encoding="utf-8", newline="") as out,
    ):
        reader, writer = csv.reader(inp), csv.writer(out)
        writer.writerow(next(reader))
        count = 0
        for row in reader:
            if count == args.n:
                break
            writer.writerow(row)
            count += 1
    print(f"{count} filas guardadas en {output}")


if __name__ == "__main__":
    main()
