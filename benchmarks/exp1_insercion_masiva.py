"""
Experimento 1: Costo de Inserción Masiva.

Comparar tiempo total y escrituras I/O al insertar lotes crecientes de
tuplas N ∈ [10^3, 10^4, 5*10^4, 10^5, 2.5*10^5, 5*10^5] en:
    Heap File, Sequential File (con y sin reorganización), Árbol B+, Hash Dinámico.

Guarda resultados crudos en benchmarks/results/exp1_results.csv
"""

N_VALUES = [10**3, 10**4, 5 * 10**4, 10**5, int(2.5 * 10**5), 5 * 10**5]


def run():
    # TODO: por cada estructura y cada N, insertar y medir:
    #   - tiempo total (segundos)
    #   - disk_writes acumulados (DiskCounter)
    raise NotImplementedError


if __name__ == "__main__":
    run()
