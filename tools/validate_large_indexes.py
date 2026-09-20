"""Construye y reabre índices públicos sobre una carga ya verificada del CSV."""

import argparse
import json
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.query_engine.executor import QueryExecutor
from backend.core.catalog.table_storage import TableStorage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/validation/500000")
    parser.add_argument("--n", type=int, default=500000)
    args = parser.parse_args()
    engine = QueryExecutor(directory=args.data_dir)
    result = {}
    for kind in ["BTREE", "HASH"]:
        name = "validation_" + kind.lower()
        if name not in [
            index.name for index in engine.schema_manager.get_table("products").indexes
        ]:
            metric = engine.execute(
                f"CREATE INDEX {name} ON products(product_id) USING {kind};"
            )
            result[kind + "_build"] = metric.to_dict()
        print("Construido", kind, flush=True)
    engine = QueryExecutor(directory=args.data_dir)
    with TableStorage(
        engine.schema_manager,
        engine.schema_manager.get_table("products"),
        engine.counter,
    ) as storage:
        btree = storage.indexes["validation_btree"]
        hash_index = storage.indexes["validation_hash"]
        expected = 1
        for rid, raw in storage.fetch_rids(btree.range_search(1, args.n)):
            assert storage.key_of(raw) == expected
            expected += 1
        assert expected == args.n + 1
        for key in [1, args.n] + random.Random(42).choices(
            range(1, args.n + 1), k=1000
        ):
            for index in [btree, hash_index]:
                rids = index.search(key)
                assert len(rids) == 1
                assert storage.key_of(storage.records.get(rids[0])) == key
        assert btree.search(args.n + 1) == hash_index.search(args.n + 1) == []
        result.update(
            {
                "rows": args.n,
                "btree_entries_verified_after_reopen": expected - 1,
                "point_queries_per_index": 1002,
                "btree_height": btree.height,
                "hash_global_depth": hash_index.global_depth,
                "verification_io_including_metadata": engine.counter.snapshot(),
            }
        )
    output = Path("benchmarks/results/large_indexes_validation.json")
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(result, flush=True)


if __name__ == "__main__":
    main()
