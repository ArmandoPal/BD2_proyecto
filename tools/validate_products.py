"""Carga N productos y compara cada registro persistido contra el CSV al reabrir."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data.load_products import load_products
from data.products import find_csv, product_rows, SERIALIZER
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.table_storage import TableStorage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv")
    parser.add_argument(
        "--sizes", type=int, nargs="+", default=[1000, 10000, 100000, 500000]
    )
    parser.add_argument("--data-dir", default="data/validation")
    parser.add_argument("--output", default="benchmarks/results/import_validation.json")
    args = parser.parse_args()
    source = find_csv(args.csv)
    results = []
    for count in args.sizes:
        directory = Path(args.data_dir) / str(count)
        result = load_products(source, count, directory)
        engine = QueryExecutor(directory=directory)
        with TableStorage(
            engine.schema_manager,
            engine.schema_manager.get_table("products"),
            engine.counter,
        ) as storage:
            expected = product_rows(source, count)
            checked = 0
            for _, raw in storage.records.scan():
                assert raw == SERIALIZER.pack(next(expected))
                checked += 1
            assert checked == count
        result["verified_rows_after_reopen"] = checked
        result["first"] = engine.execute(
            "SELECT * FROM products WHERE product_id=1;"
        ).total_rows
        result["last"] = engine.execute(
            f"SELECT * FROM products WHERE product_id={count};"
        ).total_rows
        results.append(result)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("VERIFIED", count, flush=True)


if __name__ == "__main__":
    main()
