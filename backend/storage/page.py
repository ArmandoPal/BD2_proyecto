"""
Page Layout (3.1 Capa de Almacenamiento Físico)

Define la estructura binaria de una página/bloque físico de tamaño fijo
(4096 u 8192 bytes) y el formato de su cabecera (Page Header):

    - page_id
    - record_count
    - free_space_offset
    - next_page_id / prev_page_id

Puede implementarse como:
    a) Registros de longitud fija + bitmap de presencia, o
    b) Slotted-Page Architecture (página ranurada)

Cada tupla se referencia mediante RID = <page_id, slot_number>.
"""

from dataclasses import dataclass

PAGE_SIZE = 4096  # o 8192, parametrizable para el Experimento 4


@dataclass
class PageHeader:
    page_id: int
    record_count: int
    free_space_offset: int
    next_page_id: int
    prev_page_id: int

    def pack(self) -> bytes:
        """TODO: empaquetar con struct.pack según formato fijo."""
        raise NotImplementedError

    @staticmethod
    def unpack(data: bytes) -> "PageHeader":
        """TODO: desempaquetar con struct.unpack."""
        raise NotImplementedError


class Page:
    """Representa una página en memoria (buffer) antes/después de ir a disco."""

    def __init__(self, header: PageHeader, raw_data: bytearray):
        self.header = header
        self.raw_data = raw_data  # bytearray de tamaño PAGE_SIZE

    def insert_record(self, record_bytes: bytes) -> int:
        """TODO: inserta un registro en el espacio libre. Retorna el slot asignado."""
        raise NotImplementedError

    def get_record(self, slot: int) -> bytes:
        """TODO: retorna los bytes crudos del registro en ese slot."""
        raise NotImplementedError

    def delete_record(self, slot: int) -> None:
        """TODO: marca el slot como libre (eliminación lógica)."""
        raise NotImplementedError
