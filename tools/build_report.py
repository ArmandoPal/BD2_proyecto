"""Genera tablas LaTeX desde CSV medidos y compila el informe con Tectonic o pdflatex."""

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks/results"
REPORT = ROOT / "informe"


def read(name):
    with (RESULTS / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def number(value, decimals=0):
    return f"{float(value):,.{decimals}f}".replace(",", r"\,")


def table(headers, rows, caption):
    columns = "l" + "r" * (len(headers) - 1)
    return "\n".join(
        [
            r"\begin{table}[H]\centering\small",
            r"\caption{" + caption + "}",
            r"\begin{tabular}{" + columns + "}",
            r"\toprule",
            " & ".join(headers) + r" \\",
            r"\midrule",
            *[" & ".join(row) + r" \\" for row in rows],
            r"\bottomrule\end{tabular}\end{table}",
        ]
    )


def figure(names, caption):
    width = ".49" if len(names) == 2 else ".94"
    images = "\n".join(
        r"\includegraphics[width="
        + width
        + r"\textwidth]{../benchmarks/plots/"
        + name
        + "}"
        for name in names
    )
    return (
        r"\begin{figure}[H]\centering"
        + "\n"
        + images
        + "\n"
        + r"\caption{"
        + caption
        + r"}\end{figure}"
    )


def generate():
    insertion = read("exp1_results.csv")
    point = read("exp2_summary.csv")
    ranges = read("exp3_results.csv")
    pages = read("exp4_results.csv")
    imports = json.loads(
        (RESULTS / "import_validation.json").read_text(encoding="utf-8")
    )
    sizes = [1000, 10000, 50000, 100000, 250000, 500000]
    structures = ["Heap", "Sequential", "Sequential + reorganize", "B+", "Hash"]
    if {(int(r["n"]), r["structure"]) for r in insertion} != {
        (n, s) for n in sizes for s in structures
    }:
        raise ValueError("Faltan resultados del experimento 1 completo")
    if len(point) != 4 or any(
        int(r["queries"]) != 1000 or int(r["n"]) != 100000 for r in point
    ):
        raise ValueError("El experimento 2 requiere 1000 consultas y 100000 filas")
    if len(ranges) != 15 or len(pages) != 4:
        raise ValueError("Faltan resultados de rangos o tamaños de página")
    parts = [
        r"\subsection{Validación del CSV después de reabrir}",
        table(
            ["Filas", "Verificadas", "Tiempo (s)", "Lecturas", "Escrituras"],
            [
                [
                    number(r["rows"]),
                    number(r["verified_rows_after_reopen"]),
                    number(r["seconds"], 2),
                    number(r["disk_reads"]),
                    number(r["disk_writes"]),
                ]
                for r in imports
            ],
            "Importación integrada con comprobación de PRIMARY KEY. Creación de tabla medida por separado.",
        ),
        "La comparación recorre nuevamente el CSV y el Heap reabierto; exige igualdad de los bytes serializados de cada fila y comprueba los extremos del dominio. Los resultados completos incluyen lecturas/escrituras de creación en el JSON de validación.",
        r"\clearpage\subsection{Experimento 1: costo de inserción masiva}",
    ]
    for field, decimals, caption in [
        ("seconds", 2, "Tiempo de carga por estructura, en segundos."),
        ("disk_writes", 0, "Escrituras reales de páginas por carga."),
    ]:
        values = []
        for count in sizes:
            values.append(
                [number(count)]
                + [
                    number(
                        next(
                            r[field]
                            for r in insertion
                            if int(r["n"]) == count and r["structure"] == s
                        ),
                        decimals,
                    )
                    for s in structures
                ]
            )
        parts.append(
            table(
                ["N", "Heap", "Seq.", "Seq.+reorg.", "Heap+B+", "Heap+Hash"],
                values,
                caption,
            )
        )
    parts.append(
        figure(
            ["exp1_time.png", "exp1_writes.png"],
            "Cargas completas: tiempo y escrituras, con eje vertical logarítmico.",
        )
    )
    parts.append(
        "Heap escribe la página del registro y su metadata en cada inserción. Sequential aprovecha el CSV ascendente; reorganizar añade la lectura del principal y su reescritura con espacios libres. B+ y Hash incorporan mantenimiento del índice además del payload. La cantidad de escrituras incluye inicialización y splits reales. Este workload no mide el peor caso de overflow desordenado."
    )
    parts.extend(
        [
            r"\clearpage\subsection{Experimento 2: igualdad}",
            table(
                ["Estructura", "Media I/O", "Desv. I/O", "Media ms", "Desv. ms"],
                [
                    [
                        r["structure"],
                        number(r["mean_reads"], 3),
                        number(r["std_reads"], 3),
                        number(r["mean_ms"], 4),
                        number(r["std_ms"], 4),
                    ]
                    for r in point
                ],
                "1000 consultas de igualdad sobre 100000 productos; incluye recuperar la fila.",
            ),
            figure(
                ["exp2_point.png"],
                "Media y desviación estándar poblacional; escala logarítmica.",
            ),
            "El Full Scan lee las 10000 páginas de productos en cada consulta. Sequential necesita la búsqueda binaria y la página candidata. El B+ desciende desde la raíz y recupera el payload del Heap; algunas consultas leen una hoja adicional para cerrar el rango de igualdad. Hash lee una página del directorio, un bucket y una página de datos. La desviación nula de I/O del Hash observado indica ausencia de cadenas para estas claves únicas; no es una garantía para cualquier distribución.",
            r"\clearpage\subsection{Experimento 3: selectividad de rangos}",
        ]
    )
    range_rows = []
    for fraction in [0.1, 1, 5, 10, 25]:
        selected = [
            next(
                r
                for r in ranges
                if float(r["selectivity_percent"]) == fraction
                and r["structure"] == kind
            )
            for kind in ["Heap", "Sequential", "B+"]
        ]
        range_rows.append(
            [number(fraction, 1)]
            + [number(r["disk_reads"]) for r in selected]
            + [number(r["latency_ms"], 2) for r in selected]
        )
    parts.append(
        table(
            [
                r"Sel. (\%)",
                "Heap I/O",
                "Seq. I/O",
                "B+ I/O",
                "Heap ms",
                "Seq. ms",
                "B+ ms",
            ],
            range_rows,
            "Rangos inclusivos centrados en el dominio; cardinalidad verificada en cada consulta.",
        )
    )
    parts.append(
        figure(
            ["exp3_reads.png", "exp3_time.png"],
            "Costo de rangos según selectividad, con escala vertical logarítmica.",
        )
    )
    parts.append(
        "Heap mantiene un costo de escaneo completo independientemente de cuántas filas satisfacen el predicado. Sequential y B+ incrementan sus lecturas a medida que el rango necesita más páginas. El Sequential reorganizado contiene siete productos por página, mientras el Heap de payloads del B+ contiene diez; parte de la diferencia procede de esta ocupación, además del costo de navegar el índice. Las consultas del B+ reutilizan una página de datos durante la recuperación de RID consecutivos."
    )
    parts.extend(
        [
            r"\clearpage\subsection{Experimento 4: sensibilidad al tamaño de página}",
            table(
                [
                    "Bytes",
                    "Fan-out",
                    "Altura",
                    "Páginas",
                    "I/O búsqueda",
                    "Escrituras carga",
                ],
                [
                    [
                        number(r["page_size"]),
                        r["fanout"],
                        r["height"],
                        number(r["pages"]),
                        number(r["mean_search_reads"], 3),
                        number(r["build_writes"]),
                    ]
                    for r in pages
                ],
                "Árbol B+ con 100000 claves; 1000 búsquedas. No incluye recuperar productos.",
            ),
            figure(
                ["exp4_page_size.png"],
                "Estructura y lecturas del B+ para los cuatro tamaños de página.",
            ),
            "Con 1024 bytes, el árbol requiere cuatro niveles; con los tamaños mayores, tres. Aumentar la capacidad reduce el número de nodos y las escrituras de splits. La latencia de construcción no disminuye necesariamente: el serializador procesa más entradas por nodo al aumentar el tamaño de página. La reducción de I/O debe distinguirse del costo de CPU y de la caché del SO.",
        ]
    )
    (REPORT / "secciones/resultados_generados.tex").write_text(
        "\n\n".join(parts) + "\n", encoding="utf-8"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler")
    args = parser.parse_args()
    generate()
    bundled = ROOT / ".tools/tectonic/tectonic.exe"
    compiler = args.compiler or (
        str(bundled)
        if bundled.is_file()
        else shutil.which("tectonic") or shutil.which("pdflatex")
    )
    if not compiler:
        raise SystemExit("Instala Tectonic o pdflatex, o proporciona --compiler RUTA")
    if "tectonic" in Path(compiler).name.lower():
        subprocess.run([compiler, "--keep-logs", "main.tex"], cwd=REPORT, check=True)
    else:
        for _ in range(2):
            subprocess.run(
                [compiler, "-interaction=nonstopmode", "-halt-on-error", "main.tex"],
                cwd=REPORT,
                check=True,
            )
    print(REPORT / "main.pdf")


if __name__ == "__main__":
    main()
