"""Directorio paginado de referencias a buckets; solo una página en memoria."""

import struct
from backend.core.storage.page import HEADER, PageHeader

POINTER = struct.Struct("<I")


class HashDirectory:
    def __init__(self, disk_manager):
        self.dm = disk_manager
        self.capacity = (disk_manager.page_size - HEADER.size) // POINTER.size

    def read_block(self, block):
        data = self.dm.read_page(block)
        header = PageHeader.unpack(data)
        if header.page_id != block or header.record_count > self.capacity:
            raise ValueError("Directorio corrupto")
        return [
            POINTER.unpack_from(data, HEADER.size + i * POINTER.size)[0]
            for i in range(header.record_count)
        ]

    def write_block(self, block, pointers):
        header = PageHeader(
            block, len(pointers), HEADER.size + len(pointers) * POINTER.size
        )
        data = (header.pack() + b"".join(POINTER.pack(p) for p in pointers)).ljust(
            self.dm.page_size, b"\0"
        )
        if block == self.dm.num_pages():
            self.dm.allocate_page(data)
        else:
            self.dm.write_page(block, data)

    def get(self, position):
        block, slot = divmod(position, self.capacity)
        return self.read_block(block)[slot]

    def double(self, old_size):
        # Copia incremental. La mitad alta repite los punteros de la mitad baja.
        position = old_size
        while position < old_size * 2:
            block, slot = divmod(position, self.capacity)
            target = self.read_block(block)[:slot] if slot else []
            while len(target) < self.capacity and position < old_size * 2:
                source = position - old_size
                source_block = self.read_block(source // self.capacity)
                take = min(
                    self.capacity - len(target),
                    len(source_block) - source % self.capacity,
                    old_size * 2 - position,
                )
                target.extend(
                    source_block[source % self.capacity : source % self.capacity + take]
                )
                position += take
            self.write_block(block, target)

    def redirect(self, old_id, new_id, depth, size):
        for block in range((size + self.capacity - 1) // self.capacity):
            pointers = self.read_block(block)
            changed = False
            for slot, pointer in enumerate(pointers):
                index = block * self.capacity + slot
                if pointer == old_id and index & (1 << (depth - 1)):
                    pointers[slot] = new_id
                    changed = True
            if changed:
                self.write_block(block, pointers)
