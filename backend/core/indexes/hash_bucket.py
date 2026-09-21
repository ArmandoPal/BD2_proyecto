"""Bucket de hash: profundidad local, entradas clave/RID y enlace de colisiones."""

import struct
from dataclasses import dataclass, field
from backend.core.storage.page import PageHeader, HEADER
from backend.core.storage.rid import RID

ENTRY_RID = struct.Struct("<ii")
DEPTH = struct.Struct("<I")


@dataclass
class HashBucket:
    page_id: int
    local_depth: int
    entries: list = field(default_factory=list)
    next_page_id: int = -1

    def pack(self, codec, page_size):
        body = DEPTH.pack(self.local_depth)
        body += b"".join(
            codec.pack(key) + ENTRY_RID.pack(*rid) for key, rid in self.entries
        )
        header = PageHeader(
            self.page_id, len(self.entries), HEADER.size + len(body), self.next_page_id
        )
        if HEADER.size + len(body) > page_size:
            raise ValueError("Bucket demasiado grande")
        return (header.pack() + body).ljust(page_size, b"\0")

    @classmethod
    def unpack(cls, data, codec):
        header = PageHeader.unpack(data)
        depth = DEPTH.unpack_from(data, HEADER.size)[0]
        offset = HEADER.size + DEPTH.size
        if offset + header.record_count * (codec.size + ENTRY_RID.size) > len(data):
            raise ValueError("Bucket corrupto")
        entries = []
        for _ in range(header.record_count):
            key = codec.unpack(data[offset : offset + codec.size])
            offset += codec.size
            rid = RID(*ENTRY_RID.unpack_from(data, offset))
            offset += ENTRY_RID.size
            entries.append((key, rid))
        return cls(header.page_id, depth, entries, header.next_page_id)
