"""Importa por las estructuras reales del motor; memoria de una fila y páginas."""

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.catalog.table_storage import TableStorage
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.schema_manager import identifier
from data.products import find_csv, product_rows, create_sql


def load_products(
    csv_path,
    limit,
    directory,
    table="products",
    organization="HEAP",
    page_size=4096,
    indexes=(),
    progress=True,
):
    table = identifier(table)
    engine = QueryExecutor(directory=directory, page_size=page_size)
    created = engine.execute(create_sql(table, organization))
    engine.counter.reset()
    started = time.perf_counter()
    count = 0
    with TableStorage(
        engine.schema_manager, engine.schema_manager.get_table(table), engine.counter
    ) as storage:
        for values in product_rows(csv_path, limit):
            storage.insert(values)
            count += 1
            if progress and count % 10000 == 0:
                print(
                    f"{table}: {count:,} filas, {time.perf_counter() - started:.1f} s",
                    flush=True,
                )
    result = {
        "table": table,
        "rows": count,
        "organization": organization,
        "page_size": page_size,
        "record_size": storage.serializer.record_size,
        "seconds": time.perf_counter() - started,
        **engine.counter.snapshot(),
        "csv": str(Path(csv_path).resolve()),
        "requested_rows": limit,
        "creation_disk_reads": created.disk_reads,
        "creation_disk_writes": created.disk_writes,
    }
    for kind in indexes:
        metric = engine.execute(
            f"CREATE INDEX idx_{table}_{kind.lower()} ON {table}(product_id) USING {kind};"
        )
        result[kind.lower()] = metric.to_dict()
    if limit is not None and count != limit:
        raise ValueError(
            f"CSV agotado: se importaron {count} de {limit} filas solicitadas"
        )
    output = Path(directory) / (table + ".import.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv")
    parser.add_argument("--limit", type=int, default=500000)
    parser.add_argument("--table", default="products")
    parser.add_argument(
        "--organization", choices=["HEAP", "SEQUENTIAL"], default="HEAP"
    )
    parser.add_argument("--data-dir", default="data/database")
    parser.add_argument(
        "--page-size", type=int, choices=[1024, 2048, 4096, 8192], default=4096
    )
    parser.add_argument("--indexes", nargs="*", choices=["BTREE", "HASH"], default=[])
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit debe ser positivo")
    try:
        result = load_products(
            find_csv(args.csv),
            args.limit,
            args.data_dir,
            args.table,
            args.organization,
            args.page_size,
            args.indexes,
        )
    except ValueError as error:
        parser.exit(1, str(error) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
