"""
Experimento 2: Búsquedas Puntuales de Igualdad.

1000 consultas aleatorias de igualdad sobre N=100,000 registros.
Comparar promedio y desviación estándar de I/O reads y latencia (ms):
    Full Scan (Heap) vs Búsqueda Binaria (Sequential) vs Árbol B+ vs Hash Dinámico
"""

N_QUERIES = 1000
N_RECORDS = 100_000


def run():
    # TODO: generar 1000 keys aleatorias existentes, ejecutar búsqueda en
    # cada estructura, registrar disk_reads y tiempo por consulta.
    raise NotImplementedError


if __name__ == "__main__":
    run()
