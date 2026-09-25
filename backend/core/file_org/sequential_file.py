"""Principal ordenado, búsqueda binaria por fronteras y overflow enlazado."""

import heapq
import os
import struct
from backend.core.storage.page import Page, PageHeader, HEADER
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.rid import RID
from .overflow_manager import OverflowManager, LINK, NIL

META = struct.Struct("<4sIIQd")


class SequentialFile:
    def __init__(
        self, main_dm, overflow_dm, record_size, key_of, key_codec, fill_factor=0.75
    ):
        if not 0.7 <= fill_factor <= 0.8:
            raise ValueError("fill_factor debe estar entre 0.70 y 0.80")
        self.main_dm, self.overflow_dm = main_dm, overflow_dm
        self.record_size, self.key_of, self.key_codec = record_size, key_of, key_codec
        self.fill_factor = fill_factor
        self.count = 0
        self._new_page(1, bytes(record_size))
        if main_dm.num_pages():
            magic, size, rs, self.count, self.fill_factor = META.unpack_from(
                main_dm.read_page(0), HEADER.size
            )
            if (magic, size, rs) != (b"SEQ1", main_dm.page_size, record_size):
                raise ValueError("Archivo Sequential incompatible")
        else:
            main_dm.allocate_page(self._metadata())
        self.overflow = OverflowManager(overflow_dm, record_size, key_of)

    def _metadata(self):
        return (
            PageHeader(0).pack()
            + META.pack(
                b"SEQ1",
                self.main_dm.page_size,
                self.record_size,
                self.count,
                self.fill_factor,
            )
        ).ljust(self.main_dm.page_size, b"\0")

    def _new_page(self, page_id, record):
        # Frontera persistente: no cambia aunque se borre el primer registro.
        return Page(
            page_id,
            self.record_size,
            self.main_dm.page_size,
            self.key_codec.pack(self.key_of(record)) + LINK.pack(*NIL),
        )

    def _read(self, page_id):
        page = Page.unpack(self.main_dm.read_page(page_id))
        if page.header.page_id != page_id or page.record_size != self.record_size:
            raise ValueError("Página Sequential corrupta")
        return page

    def _head(self, page):
        return RID(*LINK.unpack_from(page.metadata, self.key_codec.size))

    def _set_head(self, page, head):
        page.metadata = page.metadata[: self.key_codec.size] + LINK.pack(*head)

    # PARTE IMPORTANTE PARA EXPOSICION: BUSQUEDA BINARIA EN PRINCIPAL
    def _find_page(self, key):
        lo, hi, answer = 1, self.main_dm.num_pages() - 1, 1
        while lo <= hi:
            mid = (lo + hi) // 2
            page = self._read(mid)
            fence = self.key_codec.unpack(page.metadata[: self.key_codec.size])
            if fence <= key:
                answer, lo = mid, mid + 1
            else:
                hi = mid - 1
        return answer

    def insert(self, key, record_bytes):
        if len(record_bytes) != self.record_size or key != self.key_of(record_bytes):
            raise ValueError("Clave o longitud de registro inválida")
        last_id = self.main_dm.num_pages() - 1
        if last_id == 0:
            page = self._new_page(1, record_bytes)
            slot = page.insert_record(record_bytes)
            self.main_dm.allocate_page(page.pack())
            rid = RID(1, slot)
        else:
            last = self._read(last_id)
            last_values = list(last.items())
            # Camino de anexado para el CSV ya ordenado; no requiere búsqueda binaria.
            append = (
                bool(last_values)
                and key > self.key_of(last_values[-1][1])
                and all(
                    self.key_of(data) < key
                    for _, data in self.overflow.walk(self._head(last))
                )
            )
            page = last if append else self._read(self._find_page(key))
            occupied = list(page.items())
            if append and not page.has_space:
                page = self._new_page(last_id + 1, record_bytes)
                page.header.prev_page_id = last_id
                last.header.next_page_id = last_id + 1
                self.main_dm.write_page(last_id, last.pack())
                slot = page.insert_record(record_bytes)
                self.main_dm.allocate_page(page.pack())
                rid = RID(last_id + 1, slot)
            else:
                before = -1
                after = page.capacity
                for slot, data in occupied:
                    if self.key_of(data) < key:
                        before = slot
                    else:
                        after = slot
                        break
                # Solo ocupar un hueco que mantenga el orden físico; no mover RID.
                if before + 1 < after:
                    slot = page.insert_record(record_bytes, before + 1)
                    rid = RID(page.header.page_id, slot)
                else:
                    head, overflow_rid = self.overflow.insert(
                        self._head(page), record_bytes
                    )
                    self._set_head(page, head)
                    rid = RID(-overflow_rid.page_id - 1, overflow_rid.slot_number)
                self.main_dm.write_page(page.header.page_id, page.pack())
        self.count += 1
        self.main_dm.write_page(0, self._metadata())
        return rid

    def _page_records(self, page):
        main = ((RID(page.header.page_id, slot), data) for slot, data in page.items())
        overflow = (
            (RID(-rid.page_id - 1, rid.slot_number), data)
            for rid, data in self.overflow.walk(self._head(page))
        )
        yield from heapq.merge(main, overflow, key=lambda item: self.key_of(item[1]))

    def scan(self):
        for page_id in range(1, self.main_dm.num_pages()):
            yield from self._page_records(self._read(page_id))

    def range_search(self, key_min=None, key_max=None):
        first = self._find_page(key_min) if key_min is not None else 1
        for page_id in range(first, self.main_dm.num_pages()):
            for rid, data in self._page_records(self._read(page_id)):
                key = self.key_of(data)
                if key_max is not None and key > key_max:
                    return
                if key_min is None or key >= key_min:
                    yield rid, data

    def search(self, key):
        return list(self.range_search(key, key))

    def get(self, rid):
        if rid[0] < 0:
            data = self.overflow.heap.get(RID(-rid[0] - 1, rid[1]))
            return data[LINK.size :] if data is not None else None
        return self._read(rid[0]).get_record(rid[1])

    def delete(self, rid):
        if rid[0] < 0:
            data = self.get(rid)
            if data is None:
                return False
            page = self._read(self._find_page(self.key_of(data)))
            head = self.overflow.delete(self._head(page), RID(-rid[0] - 1, rid[1]))
            self._set_head(page, head)
        else:
            page = self._read(rid[0])
            if not page.delete_record(rid[1]):
                return False
        self.main_dm.write_page(page.header.page_id, page.pack())
        self.count -= 1
        self.main_dm.write_page(0, self._metadata())
        return True

    # PARTE IMPORTANTE PARA EXPOSICION: REORGANIZACION POR MERGE
    # Memoria acotada a páginas y cursores; nunca se carga toda la tabla.
    def reorganize(self):
        temporary = self.main_dm.filepath.with_suffix(".reorganizing")
        if temporary.exists():
            temporary.unlink()
        new_dm = DiskManager(temporary, self.main_dm.page_size, self.main_dm.counter)
        try:
            new_dm.allocate_page(self._metadata())
            page = None
            for _, record in self.scan():
                if page is None:
                    page = self._new_page(new_dm.num_pages(), record)
                    page.header.prev_page_id = (
                        page.header.page_id - 1 if page.header.page_id > 1 else -1
                    )
                if page.header.record_count >= max(
                    1, int(page.capacity * self.fill_factor)
                ):
                    page.header.next_page_id = page.header.page_id + 1
                    new_dm.allocate_page(page.pack())
                    page = self._new_page(new_dm.num_pages(), record)
                    page.header.prev_page_id = page.header.page_id - 1
                page.insert_record(record)
            if page is not None:
                new_dm.allocate_page(page.pack())
        finally:
            new_dm.close()
        path, size, counter = (
            self.main_dm.filepath,
            self.main_dm.page_size,
            self.main_dm.counter,
        )
        self.main_dm.close()
        os.replace(temporary, path)
        self.main_dm = DiskManager(path, size, counter)
        self.overflow_dm.truncate()
        self.overflow = OverflowManager(self.overflow_dm, self.record_size, self.key_of)

    def close(self):
        self.main_dm.close()
        self.overflow_dm.close()
