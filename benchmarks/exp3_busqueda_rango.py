"""
Experimento 3: Búsquedas por Rango con Selectividad Variable.

Evaluar costo de I/O y tiempo para rangos que representan
0.1%, 1%, 5%, 10% y 25% del total de tuplas.
Contrastar: Árbol B+ vs Sequential File vs Full Scan.
"""

SELECTIVITIES = [0.001, 0.01, 0.05, 0.10, 0.25]


def run():
    # TODO: por cada selectividad, construir el rango correspondiente y
    # medir disk_reads/tiempo en cada estructura.
    raise NotImplementedError


if __name__ == "__main__":
    run()
