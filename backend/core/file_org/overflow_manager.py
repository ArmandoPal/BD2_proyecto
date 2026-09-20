"""Overflow enlazado por RID; cada enlace se guarda junto al registro."""

import struct
from backend.core.storage.rid import RID
from backend.core.file_org.heap_file import HeapFile

LINK = struct.Struct("<ii")
NIL = RID(-1, -1)


class OverflowManager:
    def __init__(self, disk_manager, record_size, key_of):
        self.heap = HeapFile(disk_manager, record_size + LINK.size)
        self.key_of = key_of

    def walk(self, head):
        current = RID(*head)
        visited = 0
        while current != NIL:
            data = self.heap.get(current)
            if data is None or visited > self.heap.count:
                raise ValueError("Enlace overflow corrupto")
            yield current, data[LINK.size :]
            current = RID(*LINK.unpack_from(data))
            visited += 1

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: OVERFLOW ORDENADO Y PERSISTENTE
    # ============================================================
    def insert(self, head, record):
        key = self.key_of(record)
        previous, following = NIL, NIL
        for rid, data in self.walk(head):
            if self.key_of(data) >= key:
                following = rid
                break
            previous = rid
        new_rid = self.heap.insert(LINK.pack(*following) + record)
        if previous == NIL:
            return new_rid, new_rid
        old = self.heap.get(previous)
        self.heap.update(previous, LINK.pack(*new_rid) + old[LINK.size :])
        return RID(*head), new_rid

    def delete(self, head, target):
        previous = NIL
        for rid, _ in self.walk(head):
            if rid == target:
                following = RID(*LINK.unpack_from(self.heap.get(rid)))
                if previous != NIL:
                    data = self.heap.get(previous)
                    self.heap.update(
                        previous, LINK.pack(*following) + data[LINK.size :]
                    )
                self.heap.delete(rid)
                return following if previous == NIL else head
            previous = rid
        raise ValueError("RID no pertenece a esta cadena overflow")
