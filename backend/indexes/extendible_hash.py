"""
Hashing Dinámico en Disco (3.3 Capa de Indexación Relacional Avanzada)

Implementar Extendible Hashing (directorio + buckets en disco) o
Linear Hashing (crecimiento lineal sin directorio).

Elegir UNA de las dos técnicas y documentar la decisión en el informe.
"""

from backend.storage.disk_manager import DiskManager


class ExtendibleHash:
    def __init__(self, disk_manager: DiskManager, bucket_capacity: int):
        self.disk_manager = disk_manager
        self.bucket_capacity = bucket_capacity
        self.global_depth = 1
        self.directory: list[int] = []  # TODO: persistir en disco, no en memoria

    def insert(self, key, rid: tuple[int, int]) -> None:
        """TODO: hash(key) -> bucket; split de bucket y/o duplicar directorio si desborda."""
        raise NotImplementedError

    def search(self, key):
        """TODO: hash(key) -> directorio -> bucket -> buscar registro."""
        raise NotImplementedError

    def _split_bucket(self, bucket_page_id: int):
        """TODO: divide bucket, incrementa local_depth, duplica directorio si es necesario."""
        raise NotImplementedError
