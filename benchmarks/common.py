"""Herramientas compartidas: CSV incremental, fixtures físicos y resultados medidos."""

import argparse
import csv
import json
import struct
import time
from pathlib import Path
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.record_serializer import KeyCodec
from backend.core.file_org.heap_file import HeapFile
from backend.core.file_org.sequential_file import SequentialFile
from backend.core.indexes.bplus_tree import BPlusTree
from backend.core.indexes.extendible_hash import ExtendibleHash
from data.products import find_csv as find_csv, product_rows, SERIALIZER

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks/results"
PLOTS = ROOT / "benchmarks/plots"
WORK = ROOT / "benchmarks/work"


def arguments(description, size=100000):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--csv")
    parser.add_argument("--n", type=int, default=size)
    return parser


def key_of(data):
    return struct.unpack_from("<q", data)[0]


def records(path, count):
    seen = 0
    for values in product_rows(path, count):
        seen += 1
        yield values[0], SERIALIZER.pack(values)
    if seen != count:
        raise ValueError(f"Se esperaban {count} filas; CSV contiene {seen}")


def write_csv(name, rows):
    RESULTS.mkdir(parents=True, exist_ok=True)
    with (RESULTS / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_lines(rows, x, y, group, name, xlabel, ylabel, log=False):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOTS.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 5))
    for label in dict.fromkeys(row[group] for row in rows):
        values = [r for r in rows if r[group] == label]
        ax.plot([r[x] for r in values], [r[y] for r in values], marker="o", label=label)
    ax.set(xlabel=xlabel, ylabel=ylabel)
    if log:
        ax.set_yscale("log")
    ax.grid(alpha=0.2)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / name, dpi=160)
    plt.close(fig)


class Fixture:
    """Mismos productos en Heap/Sequential; B+ y Hash apuntan al Heap real."""

    def __init__(self, directory, page_size=4096):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.counter = DiskCounter()

        def disk(name):
            return DiskManager(self.directory / name, page_size, self.counter)

        self.heap = HeapFile(disk("heap.bin"), SERIALIZER.record_size)
        self.seq = SequentialFile(
            disk("seq.bin"),
            disk("overflow.bin"),
            SERIALIZER.record_size,
            key_of,
            KeyCodec(),
        )
        self.btree = BPlusTree(disk("btree.idx"))
        self.hash = ExtendibleHash(disk("hash.idx"))

    def close(self):
        for structure in [self.heap, self.seq, self.btree, self.hash]:
            structure.close()

    def point(self, kind, key):
        if kind == "Heap":
            return sum(
                1 for _, data in self.heap.search(lambda raw: key_of(raw) == key)
            )
        if kind == "Sequential":
            return len(self.seq.search(key))
        index = self.btree if kind == "B+" else self.hash
        return sum(1 for rid in index.search(key) if key_of(self.heap.get(rid)) == key)

    def range(self, kind, lower, upper):
        if kind == "Heap":
            return sum(
                1
                for _, data in self.heap.search(
                    lambda raw: lower <= key_of(raw) <= upper
                )
            )
        if kind == "Sequential":
            return sum(1 for _ in self.seq.range_search(lower, upper))
        # RID ordenados: retener una sola página del Heap evita lecturas repetidas.
        last_page_id, page = -1, None
        count = 0
        for rid in self.btree.range_search(lower, upper):
            if rid.page_id != last_page_id:
                last_page_id = rid.page_id
                page = self.heap.read_data_page(rid.page_id)
            data = page.get_record(rid.slot_number)
            if data is not None and lower <= key_of(data) <= upper:
                count += 1
        return count


def prepare(csv_path, count, page_size=4096):
    directory = WORK / f"products_{count}_{page_size}"
    marker = directory / "ready.json"
    fixture = Fixture(directory, page_size)
    source = {
        "csv": str(Path(csv_path).resolve()),
        "bytes": Path(csv_path).stat().st_size,
        "mtime_ns": Path(csv_path).stat().st_mtime_ns,
        "n": count,
        "page_size": page_size,
    }
    if marker.exists():
        if json.loads(marker.read_text()) != source:
            fixture.close()
            raise ValueError(
                f"Fixture corresponde a otro CSV: {directory}; use otro directorio de trabajo"
            )
        return fixture
    if fixture.heap.count:
        fixture.close()
        raise ValueError(
            f"Fixture incompleto en {directory}; elimine únicamente ese directorio y repita"
        )
    started = time.perf_counter()
    for i, (key, raw) in enumerate(records(csv_path, count), 1):
        rid = fixture.heap.insert(raw)
        fixture.seq.insert(key, raw)
        fixture.btree.insert(key, rid)
        fixture.hash.insert(key, rid)
        if i % 10000 == 0:
            print(
                f"Preparación: {i:,}/{count:,} · {time.perf_counter() - started:.1f}s",
                flush=True,
            )
    fixture.seq.reorganize()
    marker.write_text(json.dumps(source), encoding="utf-8")
    fixture.close()
    return Fixture(directory, page_size)
