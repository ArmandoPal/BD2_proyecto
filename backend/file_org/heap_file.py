"""
Heap File (3.2 Métodos de Organización de Archivos)

- Inserción: O(1) I/O, ubicando la primera página con espacio disponible
  vía Free-List, o anexando al final del archivo.
- Búsqueda: Full Table Scan, costo de P lecturas de disco.
- Eliminación: lógica con Free-List, o compactación con Move-the-last.
"""

from backend.storage.disk_manager import DiskManager


class HeapFile:
    def __init__(self, disk_manager: DiskManager):
        self.disk_manager = disk_manager
        self.free_list: list[int] = []  # TODO: persistir en disco, no solo en memoria

    def insert(self, record_bytes: bytes) -> tuple[int, int]:
        """TODO: retorna RID (page_id, slot) del registro insertado."""
        raise NotImplementedError

    def scan(self):
        """TODO: generador que recorre todas las páginas (Full Table Scan)."""
        raise NotImplementedError

    def delete(self, rid: tuple[int, int], compact: bool = False) -> None:
        """TODO: eliminación lógica (Free-List) o Move-the-last si compact=True."""
        raise NotImplementedError
