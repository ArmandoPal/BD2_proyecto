"""Estructura de un nodo B+ y su representación en una página binaria."""

import struct
from dataclasses import dataclass, field
from backend.core.storage.page import PageHeader, HEADER
from backend.core.storage.rid import RID

RID_STRUCT = struct.Struct("<ii")
CHILD = struct.Struct("<I")


@dataclass
class BPlusNode:
    page_id: int
    is_leaf: bool = True
    keys: list = field(
        default_factory=list
    )  # (clave, RID): orden total para duplicados
    children: list = field(default_factory=list)
    next_leaf_id: int = -1
    prev_leaf_id: int = -1


class NodeSerializer:
    def __init__(self, page_size, codec):
        self.page_size, self.codec = page_size, codec
        self.entry_size = codec.size + RID_STRUCT.size
        self.leaf_capacity = (page_size - HEADER.size - 1) // self.entry_size
        self.internal_capacity = (page_size - HEADER.size - 1 - CHILD.size) // (
            self.entry_size + CHILD.size
        )

    def pack(self, node):
        body = bytearray([int(node.is_leaf)])
        if not node.is_leaf:
            if len(node.children) != len(node.keys) + 1:
                raise ValueError("Nodo interno inválido")
            body += CHILD.pack(node.children[0])
        for i, (key, rid) in enumerate(node.keys):
            body += self.codec.pack(key) + RID_STRUCT.pack(*rid)
            if not node.is_leaf:
                body += CHILD.pack(node.children[i + 1])
        used = HEADER.size + len(body)
        if used > self.page_size:
            raise ValueError("Nodo B+ no cabe en página")
        header = PageHeader(
            node.page_id, len(node.keys), used, node.next_leaf_id, node.prev_leaf_id
        )
        return (header.pack() + body).ljust(self.page_size, b"\0")

    def unpack(self, data):
        header = PageHeader.unpack(data)
        kind = data[HEADER.size]
        if kind not in (0, 1):
            raise ValueError("Tipo de nodo B+ inválido")
        node = BPlusNode(
            header.page_id,
            bool(kind),
            next_leaf_id=header.next_page_id,
            prev_leaf_id=header.prev_page_id,
        )
        capacity = self.leaf_capacity if node.is_leaf else self.internal_capacity
        if header.record_count > capacity:
            raise ValueError("Nodo B+ corrupto")
        offset = HEADER.size + 1
        if not node.is_leaf:
            node.children.append(CHILD.unpack_from(data, offset)[0])
            offset += CHILD.size
        for _ in range(header.record_count):
            key = self.codec.unpack(data[offset : offset + self.codec.size])
            offset += self.codec.size
            rid = RID(*RID_STRUCT.unpack_from(data, offset))
            offset += RID_STRUCT.size
            node.keys.append((key, rid))
            if not node.is_leaf:
                node.children.append(CHILD.unpack_from(data, offset)[0])
                offset += CHILD.size
        if offset != header.free_space_offset:
            raise ValueError("Longitud de nodo B+ corrupta")
        return node
