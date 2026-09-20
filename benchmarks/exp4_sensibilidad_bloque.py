"""Experimento 4: mismo conjunto de claves y diferentes tamaños físicos de página."""

import random
import sys
import tempfile
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.common import arguments, find_csv, records, WORK, write_csv, PLOTS
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.disk_counter import DiskCounter
from backend.core.indexes.bplus_tree import BPlusTree

BLOCK_SIZES = [1024, 2048, 4096, 8192]


def run():
    args = arguments(__doc__).parse_args()
    source = find_csv(args.csv)
    rows = []
    WORK.mkdir(parents=True, exist_ok=True)
    for size in BLOCK_SIZES:
        with tempfile.TemporaryDirectory(prefix="page_", dir=WORK) as temporary:
            root = Path(temporary).resolve()
            if WORK.resolve() not in root.parents:
                raise ValueError("Directorio temporal inválido")
            counter = DiskCounter()
            tree = BPlusTree(DiskManager(root / "tree.idx", size, counter))
            started = time.perf_counter()
            for key, _ in records(source, args.n):
                tree.insert(key, (key, 0))
            build_seconds = time.perf_counter() - started
            build = counter.snapshot()
            counter.reset()
            for key in random.Random(42).choices(range(1, args.n + 1), k=1000):
                assert tree.search(key) == [(key, 0)]
            rows.append(
                {
                    "page_size": size,
                    "n": args.n,
                    "fanout": tree.order,
                    "leaf_capacity": tree.max_keys,
                    "height": tree.height,
                    "pages": tree.disk_manager.num_pages(),
                    "build_seconds": build_seconds,
                    "build_reads": build["disk_reads"],
                    "build_writes": build["disk_writes"],
                    "queries": 1000,
                    "search_reads": counter.disk_reads,
                    "mean_search_reads": counter.disk_reads / 1000,
                }
            )
            tree.close()
            print(rows[-1], flush=True)
            write_csv("exp4_results.csv", rows)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOTS.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))
    for ax, field, label in zip(
        axes,
        ["fanout", "height", "mean_search_reads"],
        ["Fan-out máximo", "Altura", "Lecturas por búsqueda"],
    ):
        ax.plot([r["page_size"] for r in rows], [r[field] for r in rows], marker="o")
        ax.set(xlabel="Página (bytes)", ylabel=label)
        ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(PLOTS / "exp4_page_size.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()
