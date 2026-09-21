"""Demo pequeña reproducible, útil antes de importar el CSV masivo."""

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.query_engine.executor import QueryExecutor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/database")
    args = parser.parse_args()
    engine = QueryExecutor(directory=args.data_dir)
    if "products_demo" in engine.schema_manager.tables:
        print("products_demo ya existe; se conservan sus datos.")
        return
    engine.execute(
        "CREATE TABLE products_demo(id INT PRIMARY KEY, name CHAR(40), price FLOAT) USING SEQUENTIAL;"
    )
    for key, name, price in [
        (10, "Teclado mecánico", 149.9),
        (20, "Monitor 24 pulgadas", 699.0),
        (30, "Mouse inalámbrico", 59.9),
        (15, "Audífonos", 89.0),
        (25, "Webcam", 120.0),
    ]:
        engine.execute(f"INSERT INTO products_demo VALUES ({key}, '{name}', {price});")
    engine.execute("CREATE INDEX demo_id ON products_demo(id) USING BTREE;")
    print(
        engine.execute(
            "SELECT * FROM products_demo WHERE id >= 10 AND id <= 25;"
        ).to_dict()
    )


if __name__ == "__main__":
    main()
