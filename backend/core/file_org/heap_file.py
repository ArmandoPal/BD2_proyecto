"""Heap con Free-List persistente de páginas con slots disponibles."""

import struct
from backend.core.storage.page import Page, PageHeader, HEADER
from backend.core.storage.rid import RID

META = struct.Struct("<4sIIiQ")


class HeapFile:
    def __init__(self, disk_manager, record_size=None):
        self.disk_manager = disk_manager
        if disk_manager.num_pages():
            magic, page_size, self.record_size, self.free_head, self.count = (
                META.unpack_from(disk_manager.read_page(0), HEADER.size)
            )
            if magic != b"HEP1" or page_size != disk_manager.page_size:
                raise ValueError("Archivo Heap incompatible")
            if record_size is not None and record_size != self.record_size:
                raise ValueError("Esquema incompatible con Heap")
        else:
            if record_size is None:
                raise ValueError("Se requiere record_size para crear Heap")
            Page(1, record_size, disk_manager.page_size)
            self.record_size, self.free_head, self.count = record_size, -1, 0
            disk_manager.allocate_page(self._metadata())

    def _metadata(self):
        data = PageHeader(0).pack() + META.pack(
            b"HEP1",
            self.disk_manager.page_size,
            self.record_size,
            self.free_head,
            self.count,
        )
        return data.ljust(self.disk_manager.page_size, b"\0")

    def _save(self):
        self.disk_manager.write_page(0, self._metadata())

    def read_data_page(self, page_id):
        page = Page.unpack(self.disk_manager.read_page(page_id))
        if page.header.page_id != page_id or page.record_size != self.record_size:
            raise ValueError("Página Heap corrupta")
        return page

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: HEAP INSERT Y FREE-LIST
    # La cabecera apunta a la primera página libre; no recorre el archivo.
    # ============================================================
    def insert(self, record_bytes):
        if len(record_bytes) != self.record_size:
            raise ValueError("Registro de tamaño incorrecto")
        if self.free_head == -1:
            page = Page(
                self.disk_manager.num_pages(),
                self.record_size,
                self.disk_manager.page_size,
            )
            slot = page.insert_record(record_bytes)
            self.disk_manager.allocate_page(page.pack())
            if page.has_space:
                self.free_head = page.header.page_id
        else:
            page = self.read_data_page(self.free_head)
            slot = page.insert_record(record_bytes)
            if not page.has_space:
                self.free_head = page.header.next_page_id
                page.header.next_page_id = -1
            self.disk_manager.write_page(page.header.page_id, page.pack())
        self.count += 1
        self._save()
        return RID(page.header.page_id, slot)

    def get(self, rid):
        return self.read_data_page(rid[0]).get_record(rid[1])

    def update(self, rid, data):
        page = self.read_data_page(rid[0])
        page.update_record(rid[1], data)
        self.disk_manager.write_page(rid[0], page.pack())

    def scan(self):
        for page_id in range(1, self.disk_manager.num_pages()):
            for slot, data in self.read_data_page(page_id).items():
                yield RID(page_id, slot), data

    def search(self, predicate):
        return ((rid, data) for rid, data in self.scan() if predicate(data))

    def delete(self, rid):
        page = self.read_data_page(rid[0])
        was_full = not page.has_space
        if not page.delete_record(rid[1]):
            return False
        if was_full:
            page.header.next_page_id = self.free_head
            self.free_head = rid[0]
        self.disk_manager.write_page(rid[0], page.pack())
        self.count -= 1
        self._save()
        return True

    def close(self):
        self.disk_manager.close()
