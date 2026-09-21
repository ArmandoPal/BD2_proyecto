"""B+ multinivel: descenso por páginas, split recursivo y hojas enlazadas."""

import struct
from bisect import bisect_left, bisect_right
from backend.core.storage.page import PageHeader, HEADER
from backend.core.storage.record_serializer import KeyCodec
from backend.core.storage.rid import RID
from .bplus_node import BPlusNode, NodeSerializer

META = struct.Struct("<4sIIII32s")
MIN_RID = RID(-(2**31), -(2**31))


class BPlusTree:
    def __init__(self, disk_manager, order=None, key_type="INT"):
        self.disk_manager = disk_manager
        self.codec = KeyCodec(key_type)
        self.serializer = NodeSerializer(disk_manager.page_size, self.codec)
        maximum = min(self.serializer.leaf_capacity, self.serializer.internal_capacity)
        self.max_keys = maximum if order is None else order - 1
        if not 3 <= self.max_keys <= maximum:
            raise ValueError("Orden B+ incompatible con página o clave")
        self.order = self.max_keys + 1
        self.root_page_id = 1
        self.height = 1
        if disk_manager.num_pages():
            magic, size, self.root_page_id, stored, self.height, dtype = (
                META.unpack_from(disk_manager.read_page(0), HEADER.size)
            )
            if (
                magic != b"BPT1"
                or size != disk_manager.page_size
                or dtype.rstrip(b"\0").decode() != key_type
            ):
                raise ValueError("Índice B+ incompatible")
            if order is not None and stored != self.max_keys:
                raise ValueError("Orden B+ incompatible")
            self.max_keys, self.order = stored, stored + 1
        else:
            disk_manager.allocate_page(self._metadata())
            disk_manager.allocate_page(self.serializer.pack(BPlusNode(1)))

    def _metadata(self):
        return (
            PageHeader(0).pack()
            + META.pack(
                b"BPT1",
                self.disk_manager.page_size,
                self.root_page_id,
                self.max_keys,
                self.height,
                self.codec.dtype.encode(),
            )
        ).ljust(self.disk_manager.page_size, b"\0")

    def _read_node(self, page_id):
        node = self.serializer.unpack(self.disk_manager.read_page(page_id))
        if node.page_id != page_id:
            raise ValueError("Identificador de nodo corrupto")
        return node

    def _write_node(self, node):
        self.disk_manager.write_page(node.page_id, self.serializer.pack(node))

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: BUSQUEDA B+ DESDE LA RAIZ
    # ============================================================
    def _find_leaf(self, entry):
        path = []
        node = self._read_node(self.root_page_id)
        while not node.is_leaf:
            path.append(node.page_id)
            node = self._read_node(node.children[bisect_right(node.keys, entry)])
        return node, path

    def insert(self, key, rid):
        self.codec.pack(key)
        entry = (key, RID(*rid))
        leaf, path = self._find_leaf(entry)
        self._insert_into_leaf(leaf, entry)
        if len(leaf.keys) <= self.max_keys:
            self._write_node(leaf)
        else:
            self._split_leaf(leaf, path)

    def _insert_into_leaf(self, leaf, entry):
        position = bisect_left(leaf.keys, entry)
        if position < len(leaf.keys) and leaf.keys[position] == entry:
            raise ValueError("Par clave/RID duplicado")
        leaf.keys.insert(position, entry)

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: SPLIT DE UNA HOJA DEL ARBOL B+
    # ============================================================
    def _split_leaf(self, leaf, path):
        middle = len(leaf.keys) // 2
        right = BPlusNode(
            self.disk_manager.num_pages(),
            keys=leaf.keys[middle:],
            next_leaf_id=leaf.next_leaf_id,
            prev_leaf_id=leaf.page_id,
        )
        leaf.keys = leaf.keys[:middle]
        leaf.next_leaf_id = right.page_id
        self.disk_manager.allocate_page(self.serializer.pack(right))
        if right.next_leaf_id != -1:
            following = self._read_node(right.next_leaf_id)
            following.prev_leaf_id = right.page_id
            self._write_node(following)
        self._write_node(leaf)
        self._insert_into_parent(leaf.page_id, right.keys[0], right.page_id, path)

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: PROPAGACION DEL SPLIT
    # ============================================================
    def _insert_into_parent(self, left_id, separator, right_id, path):
        if not path:
            root = BPlusNode(
                self.disk_manager.num_pages(), False, [separator], [left_id, right_id]
            )
            self.disk_manager.allocate_page(self.serializer.pack(root))
            self.root_page_id = root.page_id
            self.height += 1
            self.disk_manager.write_page(0, self._metadata())
            return
        parent = self._read_node(path.pop())
        position = parent.children.index(left_id)
        parent.keys.insert(position, separator)
        parent.children.insert(position + 1, right_id)
        if len(parent.keys) <= self.max_keys:
            self._write_node(parent)
        else:
            self._split_internal(parent, path)

    def _split_internal(self, node, path):
        middle = len(node.keys) // 2
        promoted = node.keys[middle]
        right = BPlusNode(
            self.disk_manager.num_pages(),
            False,
            node.keys[middle + 1 :],
            node.children[middle + 1 :],
        )
        node.keys, node.children = node.keys[:middle], node.children[: middle + 1]
        self.disk_manager.allocate_page(self.serializer.pack(right))
        self._write_node(node)
        self._insert_into_parent(node.page_id, promoted, right.page_id, path)

    def search(self, key):
        return list(self.range_search(key, key))

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: RANGO POR HOJAS ENLAZADAS
    # ============================================================
    def range_search(self, min_key=None, max_key=None):
        if min_key is None:
            leaf = self._read_node(self.root_page_id)
            while not leaf.is_leaf:
                leaf = self._read_node(leaf.children[0])
            position = 0
        else:
            leaf, _ = self._find_leaf((min_key, MIN_RID))
            position = bisect_left(leaf.keys, (min_key, MIN_RID))
        while True:
            for key, rid in leaf.keys[position:]:
                if max_key is not None and key > max_key:
                    return
                yield rid
            if leaf.next_leaf_id == -1:
                return
            leaf = self._read_node(leaf.next_leaf_id)
            position = 0

    def delete(self, key, rid):
        # Sin merge: separadores siguen siendo límites válidos; hojas vacías permanecen enlazadas.
        entry = (key, RID(*rid))
        leaf, _ = self._find_leaf(entry)
        position = bisect_left(leaf.keys, entry)
        if position == len(leaf.keys) or leaf.keys[position] != entry:
            return False
        leaf.keys.pop(position)
        self._write_node(leaf)
        return True

    def close(self):
        self.disk_manager.close()
