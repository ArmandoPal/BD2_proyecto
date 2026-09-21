"""Experimento 2: 1000 consultas reproducibles sobre 100000 productos."""

import random
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.common import arguments, find_csv, prepare, write_csv, PLOTS


def run():
    parser = arguments(__doc__)
    parser.add_argument("--queries", type=int, default=1000)
    args = parser.parse_args()
    fixture = prepare(find_csv(args.csv), args.n)
    keys = random.Random(42).choices(range(1, args.n + 1), k=args.queries)
    raw_rows = []
    summary = []
    try:
        for kind in ["Heap", "Sequential", "B+", "Hash"]:
            for number, key in enumerate(keys, 1):
                fixture.counter.reset()
                started = time.perf_counter()
                found = fixture.point(kind, key)
                elapsed = (time.perf_counter() - started) * 1000
                assert found == 1, (kind, key, found)
                raw_rows.append(
                    {
                        "structure": kind,
                        "n": args.n,
                        "query": number,
                        "key": key,
                        "latency_ms": elapsed,
                        **fixture.counter.snapshot(),
                    }
                )
                if number % 100 == 0:
                    print(f"{kind}: {number}/{args.queries}", flush=True)
            values = [r for r in raw_rows if r["structure"] == kind]
            summary.append(
                {
                    "structure": kind,
                    "n": args.n,
                    "queries": args.queries,
                    "mean_reads": statistics.mean(r["disk_reads"] for r in values),
                    "std_reads": statistics.pstdev(r["disk_reads"] for r in values),
                    "mean_ms": statistics.mean(r["latency_ms"] for r in values),
                    "std_ms": statistics.pstdev(r["latency_ms"] for r in values),
                }
            )
            write_csv("exp2_raw.csv", raw_rows)
            write_csv("exp2_summary.csv", summary)
            print(summary[-1], flush=True)
    finally:
        fixture.close()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    PLOTS.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    for ax, mean, std, label in [
        (axes[0], "mean_reads", "std_reads", "Lecturas promedio"),
        (axes[1], "mean_ms", "std_ms", "Latencia promedio (ms)"),
    ]:
        ax.bar(
            [r["structure"] for r in summary],
            [r[mean] for r in summary],
            yerr=[r[std] for r in summary],
            capsize=4,
            color=["#8597b9", "#73b5a4", "#8da6f0", "#b69bd6"],
        )
        ax.set_yscale("log")
        ax.set_ylabel(label)
        ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(PLOTS / "exp2_point.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    run()
