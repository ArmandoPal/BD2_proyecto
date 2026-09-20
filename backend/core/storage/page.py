"""Página de registros fijos: cabecera, configuración, metadata, bitmap y slots."""

import struct
from dataclasses import dataclass

PAGE_SIZE = 4096
HEADER = struct.Struct("<IIIii")
LAYOUT = struct.Struct("<III")


@dataclass
class PageHeader:
    page_id: int
    record_count: int = 0
    free_space_offset: int = 0
    next_page_id: int = -1
    prev_page_id: int = -1

    def pack(self):
        return HEADER.pack(
            self.page_id,
            self.record_count,
            self.free_space_offset,
            self.next_page_id,
            self.prev_page_id,
        )

    @classmethod
    def unpack(cls, data):
        if len(data) < HEADER.size:
            raise ValueError("Cabecera truncada")
        return cls(*HEADER.unpack_from(data))


class Page:
    def __init__(self, page_id, record_size, page_size=PAGE_SIZE, metadata=b""):
        self.record_size = record_size
        self.page_size = page_size
        self.metadata = bytes(metadata)
        self.capacity = (page_size - HEADER.size - LAYOUT.size - len(metadata)) // (
            record_size + 1
        )
        if record_size <= 0 or self.capacity < 1:
            raise ValueError("El registro no cabe en la página")
        self.header = PageHeader(page_id)
        self.bitmap = bytearray(self.capacity)
        self.records = bytearray(self.capacity * record_size)
        self._update_free_offset()

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: PAGE LAYOUT Y OFFSET DEL SLOT
    # ============================================================
    @property
    def records_offset(self):
        return HEADER.size + LAYOUT.size + len(self.metadata) + self.capacity

    def _update_free_offset(self):
        slot = self.bitmap.find(0)
        self.header.free_space_offset = (
            self.records_offset + slot * self.record_size
            if slot >= 0
            else self.page_size
        )

    @property
    def has_space(self):
        return self.header.record_count < self.capacity

    def insert_record(self, record_bytes, slot=None):
        if len(record_bytes) != self.record_size:
            raise ValueError("Longitud de registro incorrecta")
        if slot is None:
            slot = self.bitmap.find(0)
        if not 0 <= slot < self.capacity or self.bitmap[slot]:
            raise ValueError("Slot ocupado o página llena")
        start = slot * self.record_size
        self.records[start : start + self.record_size] = record_bytes
        self.bitmap[slot] = 1
        self.header.record_count += 1
        self._update_free_offset()
        return slot

    def get_record(self, slot):
        if not 0 <= slot < self.capacity:
            raise ValueError("Slot fuera de rango")
        if not self.bitmap[slot]:
            return None
        start = slot * self.record_size
        return bytes(self.records[start : start + self.record_size])

    def update_record(self, slot, record_bytes):
        if self.get_record(slot) is None or len(record_bytes) != self.record_size:
            raise ValueError("Actualización de slot inválida")
        start = slot * self.record_size
        self.records[start : start + self.record_size] = record_bytes

    def delete_record(self, slot):
        if self.get_record(slot) is None:
            return False
        self.bitmap[slot] = 0
        self.header.record_count -= 1
        self._update_free_offset()
        return True

    def items(self):
        for slot, used in enumerate(self.bitmap):
            if used:
                yield slot, self.get_record(slot)

    def pack(self):
        data = (
            self.header.pack()
            + LAYOUT.pack(self.record_size, self.capacity, len(self.metadata))
            + self.metadata
            + self.bitmap
            + self.records
        )
        return bytes(data).ljust(self.page_size, b"\0")

    @classmethod
    def unpack(cls, data):
        if len(data) < HEADER.size + LAYOUT.size:
            raise ValueError("Página truncada")
        header = PageHeader.unpack(data)
        size, capacity, meta_size = LAYOUT.unpack_from(data, HEADER.size)
        start = HEADER.size + LAYOUT.size
        if meta_size > len(data) - start:
            raise ValueError("Metadata de página inválida")
        page = cls(header.page_id, size, len(data), data[start : start + meta_size])
        if page.capacity != capacity:
            raise ValueError("Capacidad de página corrupta")
        start += meta_size
        page.bitmap = bytearray(data[start : start + capacity])
        if (
            any(x not in (0, 1) for x in page.bitmap)
            or sum(page.bitmap) != header.record_count
        ):
            raise ValueError("Bitmap de página corrupto")
        page.records = bytearray(
            data[page.records_offset : page.records_offset + capacity * size]
        )
        page._update_free_offset()
        if header.free_space_offset != page.header.free_space_offset:
            raise ValueError("Offset de espacio libre corrupto")
        page.header = header
        return page
