"""Experimento 3: rangos inclusivos con selectividad entre 0.1% y 25%."""

import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.common import arguments, find_csv, prepare, write_csv, plot_lines

SELECTIVITIES = [0.001, 0.01, 0.05, 0.10, 0.25]


def run():
    args = arguments(__doc__).parse_args()
    fixture = prepare(find_csv(args.csv), args.n)
    rows = []
    try:
        for fraction in SELECTIVITIES:
            width = max(1, int(args.n * fraction))
            lower = max(1, (args.n - width) // 2)
            upper = lower + width - 1
            for kind in ["Heap", "Sequential", "B+"]:
                fixture.counter.reset()
                started = time.perf_counter()
                found = fixture.range(kind, lower, upper)
                elapsed = (time.perf_counter() - started) * 1000
                assert found == width, (kind, found, width)
                rows.append(
                    {
                        "structure": kind,
                        "n": args.n,
                        "selectivity_percent": fraction * 100,
                        "lower": lower,
                        "upper": upper,
                        "rows": found,
                        "latency_ms": elapsed,
                        **fixture.counter.snapshot(),
                    }
                )
                print(rows[-1], flush=True)
    finally:
        fixture.close()
    write_csv("exp3_results.csv", rows)
    plot_lines(
        rows,
        "selectivity_percent",
        "disk_reads",
        "structure",
        "exp3_reads.png",
        "Selectividad (%)",
        "Páginas leídas",
        True,
    )
    plot_lines(
        rows,
        "selectivity_percent",
        "latency_ms",
        "structure",
        "exp3_time.png",
        "Selectividad (%)",
        "Latencia (ms)",
        True,
    )


if __name__ == "__main__":
    run()
