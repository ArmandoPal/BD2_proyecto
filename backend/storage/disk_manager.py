"""
Disk Manager (3.1 Capa de Almacenamiento Físico)

Responsable exclusivo de la interacción binaria con el archivo en disco:
seek(offset) + struct para leer/escribir páginas completas.

Prohibido: pickle, lectura global con .read() sin offsets.
Todo acceso a disco del sistema (Heap, Sequential, B+, Hash) DEBE pasar
por este módulo para que DiskCounter registre correctamente disk_reads
y disk_writes.
"""

import os
from .page import PAGE_SIZE
from .disk_counter import DiskCounter


class DiskManager:
    def __init__(self, filepath: str, page_size: int = PAGE_SIZE, counter: DiskCounter = None):
        self.filepath = filepath
        self.page_size = page_size
        self.counter = counter or DiskCounter()
        if not os.path.exists(filepath):
            open(filepath, "wb").close()

    def read_page(self, page_id: int) -> bytes:
        """TODO: seek(page_id * page_size) + read(page_size). Incrementa disk_reads."""
        raise NotImplementedError

    def write_page(self, page_id: int, data: bytes) -> None:
        """TODO: seek(page_id * page_size) + write(data). Incrementa disk_writes."""
        raise NotImplementedError

    def allocate_page(self) -> int:
        """TODO: retorna un nuevo page_id (al final del archivo) y lo inicializa."""
        raise NotImplementedError

    def num_pages(self) -> int:
        """TODO: tamaño_archivo // page_size."""
        raise NotImplementedError
