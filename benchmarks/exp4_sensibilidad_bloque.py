"""
Experimento 4: Sensibilidad al Tamaño de Bloque.

Variar B ∈ [1024, 2048, 4096, 8192] bytes y analizar el efecto en:
    - factor de ramificación (fan-out) del B+
    - altura h del árbol B+
    - número total de I/Os transferidos
"""

BLOCK_SIZES = [1024, 2048, 4096, 8192]


def run():
    # TODO: reconstruir el árbol B+ con cada page_size, registrar fan-out,
    # altura resultante y total de I/Os para una carga fija de datos.
    raise NotImplementedError


if __name__ == "__main__":
    run()
