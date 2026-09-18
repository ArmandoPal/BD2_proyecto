"""
Árbol B+ multinivel en disco (3.3 Capa de Indexación Relacional Avanzada)

- Nodos internos: <P0, K1, P1, ..., Km, Pm> (claves separadoras + punteros).
- Nodos hoja: pares ordenados <Key_i, RID_i> (o registro completo si es
  índice agrupado), con next_leaf_id / prev_leaf_id enlazados.
- Insertar: split recursivo al 50% con propagación al padre.
- Buscar puntual: costo O(log_M N) transferencias de disco.
- Buscar por rango: desciende a la primera hoja y recorre next_leaf.
"""

from backend.storage.disk_manager import DiskManager


class BPlusTree:
    def __init__(self, disk_manager: DiskManager, order: int):
        self.disk_manager = disk_manager
        self.order = order  # M: fan-out máximo, depende del PAGE_SIZE (Exp. 4)
        self.root_page_id: int | None = None

    def insert(self, key, rid: tuple[int, int]) -> None:
        """TODO: descender hasta la hoja correcta, insertar, split si desborda."""
        raise NotImplementedError

    def search(self, key):
        """TODO: búsqueda puntual descendiendo desde la raíz."""
        raise NotImplementedError

    def range_search(self, key_min, key_max):
        """TODO: descender a la primera hoja >= key_min, recorrer next_leaf_id."""
        raise NotImplementedError

    def _split_leaf(self, leaf_page_id: int):
        """TODO: divide la hoja al 50%, propaga clave separadora al padre."""
        raise NotImplementedError

    def _split_internal(self, node_page_id: int):
        """TODO: divide nodo interno, crea nueva raíz si es necesario."""
        raise NotImplementedError
