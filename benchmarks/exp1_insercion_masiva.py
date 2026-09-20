"""Experimento 1: inserción de registros completos sobre archivos nuevos."""

import argparse
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.common import (
    WORK,
    records,
    find_csv,
    SERIALIZER,
    key_of,
    write_csv,
    plot_lines,
)
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.record_serializer import KeyCodec
from backend.core.file_org.heap_file import HeapFile
from backend.core.file_org.sequential_file import SequentialFile
from backend.core.indexes.bplus_tree import BPlusTree
from backend.core.indexes.extendible_hash import ExtendibleHash

N_VALUES = [1000, 10000, 50000, 100000, 250000, 500000]


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv")
    parser.add_argument("--sizes", type=int, nargs="+", default=N_VALUES)
    args = parser.parse_args()
    source = find_csv(args.csv)
    rows = []
    WORK.mkdir(parents=True, exist_ok=True)
    for count in args.sizes:
        for kind in ["Heap", "Sequential", "Sequential + reorganize", "B+", "Hash"]:
            with tempfile.TemporaryDirectory(prefix="insert_", dir=WORK) as temporary:
                root = Path(temporary).resolve()
                if WORK.resolve() not in root.parents:
                    raise ValueError("Directorio temporal fuera del workspace")
                counter = DiskCounter()
                index = None

                def disk(name):
                    return DiskManager(root / name, 4096, counter)

                started = time.perf_counter()
                if kind.startswith("Sequential"):
                    table = SequentialFile(
                        disk("main.bin"),
                        disk("overflow.bin"),
                        SERIALIZER.record_size,
                        key_of,
                        KeyCodec(),
                    )
                else:
                    table = HeapFile(disk("heap.bin"), SERIALIZER.record_size)
                if kind == "B+":
                    index = BPlusTree(disk("index.idx"))
                if kind == "Hash":
                    index = ExtendibleHash(disk("index.idx"))
                for key, raw in records(source, count):
                    rid = (
                        table.insert(key, raw)
                        if kind.startswith("Sequential")
                        else table.insert(raw)
                    )
                    if index:
                        index.insert(key, rid)
                if kind == "Sequential + reorganize":
                    table.reorganize()
                elapsed = time.perf_counter() - started
                row = {
                    "structure": kind,
                    "n": count,
                    "seconds": elapsed,
                    **counter.snapshot(),
                    "scope": "tabla+indice" if index else "tabla",
                    "input_order": "CSV ascendente",
                    "page_size": 4096,
                    "record_size": SERIALIZER.record_size,
                }
                if index:
                    index.close()
                table.close()
                rows.append(row)
                write_csv("exp1_results.csv", rows)
                print(row, flush=True)
    plot_lines(
        rows,
        "n",
        "seconds",
        "structure",
        "exp1_time.png",
        "Registros",
        "Tiempo de carga (s)",
        True,
    )
    plot_lines(
        rows,
        "n",
        "disk_writes",
        "structure",
        "exp1_writes.png",
        "Registros",
        "Escrituras de páginas",
        True,
    )


if __name__ == "__main__":
    run()
