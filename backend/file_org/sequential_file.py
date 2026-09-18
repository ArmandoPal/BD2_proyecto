"""
Sequential File (3.2 Métodos de Organización de Archivos)

- Área de Datos Principal: páginas ordenadas físicamente por clave primaria,
  admite búsqueda binaria.
- Área de Desbordamiento (Overflow): tuplas que no entran en su bloque
  principal, enlazadas con punteros binarios manteniendo el orden lógico.
- reorganize(): fusiona ambas áreas, reescribe archivo principal limpio
  con fill factor de 70-80%, vacía el overflow.
"""

from backend.storage.disk_manager import DiskManager


class SequentialFile:
    def __init__(self, main_dm: DiskManager, overflow_dm: DiskManager, fill_factor: float = 0.75):
        self.main_dm = main_dm
        self.overflow_dm = overflow_dm
        self.fill_factor = fill_factor

    def insert(self, key, record_bytes: bytes) -> tuple[int, int]:
        """TODO: inserta en el área principal si hay espacio, si no en overflow enlazado."""
        raise NotImplementedError

    def search(self, key):
        """TODO: búsqueda binaria en área principal + recorrido de overflow enlazado."""
        raise NotImplementedError

    def range_search(self, key_min, key_max):
        """TODO: búsqueda binaria del límite inferior + recorrido secuencial."""
        raise NotImplementedError

    def reorganize(self) -> None:
        """TODO: merge ordenado de principal + overflow, reescribe con fill_factor."""
        raise NotImplementedError
