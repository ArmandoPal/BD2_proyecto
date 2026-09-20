"""Multilevel B+ tree on disk (enunciado 3.3.1).

One node per page, so the fan-out M follows directly from the block size::

    leaf      <Key, RID> pairs, sorted, plus next_leaf / prev_leaf pointers
    internal  <P0, K1, P1, ... Km, Pm>: P0 lives in the page's next_page_id
              field and every <Ki, Pi> pair is a record in the page

Costs:
    point search   h = O(log_M N) block reads
    range search   h reads to reach the first leaf, then one read per leaf
                   followed through next_leaf
    insert         split at 50% with recursive propagation, new root on overflow

Deletion removes the entry from its leaf but does not merge or redistribute
nodes: the tree can get sparser over time, which is why the engine exposes
``rebuild()``. Lookups stay correct throughout.
"""

import struct
from bisect import bisect_left, bisect_right

from backend.catalog.record import RID_SIZE, pack_rid, unpack_rid
from backend.storage import NULL_PAGE, PageType

from .base import IndexFile

CHILD_FORMAT = "<I"
CHILD_SIZE = struct.calcsize(CHILD_FORMAT)


class _KeyView:
    """sorted, read-only view of a node's keys so bisect decodes only the slots it probes.

    A node holds up to M keys; materializing all of them to find one child turns an
    O(log M) search into O(M) struct.unpack calls. This view keeps the descent
    logarithmic in work as well as in block reads.
    """

    __slots__ = ("tree", "page")

    def __init__(self, tree, page):
        """wraps one node page without reading any of its records yet."""
        self.tree = tree
        self.page = page

    def __len__(self):
        """number of entries in the node; B+ nodes never carry tombstones."""
        return self.page.slot_count

    def __getitem__(self, index):
        """decodes the key of a single slot, which is all bisect needs."""
        return self.tree.unpack_key(self.page.get_record(index))


class BPlusTree(IndexFile):
    """balanced multilevel index where every node is one disk block."""

    def __init__(self, *args, **kwargs):
        """opens the index and clears the cached key span used for selectivity estimates."""
        super().__init__(*args, **kwargs)
        self._span = None

    # ---------- entry encoding ----------

    def _leaf_entry(self, key, rid):
        """builds a leaf record: the packed key followed by its 6-byte RID."""
        return self.pack_key(key) + pack_rid(rid)

    def _leaf_rid(self, entry):
        """reads the RID out of a leaf record."""
        return unpack_rid(entry[self.key_size:self.key_size + RID_SIZE])

    def _internal_entry(self, key, child):
        """builds an internal record: the separator key followed by its right child page id."""
        return self.pack_key(key) + struct.pack(CHILD_FORMAT, child)

    def _internal_child(self, entry):
        """reads the child page id out of an internal record."""
        (child,) = struct.unpack(CHILD_FORMAT, entry[self.key_size:self.key_size + CHILD_SIZE])
        return child

    def _keys(self, page):
        """returns the keys of a node in slot order, which is sorted order."""
        return [self.unpack_key(entry) for entry in page.records()]

    # ---------- fan-out ----------

    def fan_out(self):
        """maximum number of children an internal node holds, i.e. the branching factor M."""
        from backend.storage import HEADER_SIZE, SLOT_SIZE
        usable = self.page_size - HEADER_SIZE
        return usable // (self.key_size + CHILD_SIZE + SLOT_SIZE) + 1

    def leaf_capacity(self):
        """maximum number of <key, RID> pairs one leaf can hold."""
        from backend.storage import HEADER_SIZE, SLOT_SIZE
        return (self.page_size - HEADER_SIZE) // (self.leaf_entry_size + SLOT_SIZE)

    # ---------- search ----------

    def _descend(self, key):
        """walks from the root to the leaf that would contain `key`, costing h block reads."""
        page_id = self.root_page_id
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                if page.page_type is PageType.BTREE_LEAF:
                    return page_id
                page_id = self._child_for(page, key)
        return NULL_PAGE

    def _child_for(self, page, key):
        """picks the child pointer to follow: P0 when key is below K1, otherwise the last Ki <= key."""
        position = bisect_right(_KeyView(self, page), key)
        if position == 0:
            return page.next_page_id          # P0, the leftmost child
        return self._internal_child(page.get_record(position - 1))

    def search(self, key):
        """returns every RID stored under a key, following leaf links when duplicates spill over."""
        page_id = self._descend(key)
        found = []
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                keys = _KeyView(self, page)
                count = len(keys)
                start = bisect_left(keys, key)
                for position in range(start, count):
                    entry = page.get_record(position)
                    if self.unpack_key(entry) != key:
                        return found
                    found.append(self._leaf_rid(entry))
                if not count or keys[count - 1] != key:
                    return found
                page_id = page.next_page_id
        return found

    def range_search(self, low, high):
        """descends to the first leaf at or above `low`, then follows next_leaf while keys fit."""
        if low is not None and high is not None and low > high:
            return []
        page_id = self._descend(low) if low is not None else self._leftmost_leaf()
        found = []
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                entries = page.records()
                start = bisect_left(_KeyView(self, page), low) if low is not None else 0
                for position in range(start, len(entries)):
                    entry = entries[position]
                    key = self.unpack_key(entry)
                    if high is not None and key > high:
                        return found
                    found.append((key, self._leaf_rid(entry)))
                page_id = page.next_page_id
        return found

    def _leftmost_leaf(self):
        """walks down the leftmost pointers to the first leaf, the start of a full ordered scan."""
        page_id = self.root_page_id
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                if page.page_type is PageType.BTREE_LEAF:
                    return page_id
                page_id = page.next_page_id
        return NULL_PAGE

    def scan(self):
        """yields every <key, RID> in key order by following the leaf chain."""
        return self.range_search(None, None)

    def _rightmost_leaf(self):
        """walks down the last child pointer of every node to reach the last leaf."""
        page_id = self.root_page_id
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                if page.page_type is PageType.BTREE_LEAF:
                    return page_id
                entries = page.records()
                page_id = self._internal_child(entries[-1]) if entries else page.next_page_id
        return NULL_PAGE

    def key_span(self):
        """returns the smallest and largest key in the tree, so the planner can estimate selectivity."""
        if self._span is not None:
            return self._span
        first, last = self._leftmost_leaf(), self._rightmost_leaf()
        if first == NULL_PAGE:
            return None
        with self.pool.get(first) as page:
            entries = page.records()
            low = self.unpack_key(entries[0]) if entries else None
        with self.pool.get(last) as page:
            entries = page.records()
            high = self.unpack_key(entries[-1]) if entries else None
        self._span = (low, high) if low is not None and high is not None else None
        return self._span

    # ---------- insert ----------

    def insert(self, key, rid):
        """inserts a <key, RID> pair, splitting nodes upward and growing a new root on overflow."""
        if self.root_page_id == NULL_PAGE:
            with self.pool.allocate(PageType.BTREE_LEAF) as leaf:
                leaf.insert_record(self._leaf_entry(key, rid), at=0)
                self.root_page_id = leaf.page_id
            self.depth = 1
            self.num_entries += 1
            self._span = None
            return

        promoted = self._insert_into(self.root_page_id, key, rid)
        if promoted is not None:
            separator, right_id = promoted
            with self.pool.allocate(PageType.BTREE_INTERNAL) as root:
                root.next_page_id = self.root_page_id          # P0
                root.insert_record(self._internal_entry(separator, right_id), at=0)
                self.root_page_id = root.page_id
            self.depth += 1
        self.num_entries += 1
        self._span = None

    def _insert_into(self, page_id, key, rid):
        """recursive insert; returns <separator, new_page_id> when this node had to split."""
        with self.pool.modify(page_id) as page:
            is_leaf = page.page_type is PageType.BTREE_LEAF
            if is_leaf:
                entry = self._leaf_entry(key, rid)
                position = bisect_right(_KeyView(self, page), key)
                if page.can_fit(len(entry)):
                    page.insert_record(entry, at=position)
                    return None
                return self._split_leaf(page, entry, position)
            child_id = self._child_for(page, key)

        promoted = self._insert_into(child_id, key, rid)
        if promoted is None:
            return None

        separator, right_id = promoted
        with self.pool.modify(page_id) as page:
            entry = self._internal_entry(separator, right_id)
            position = bisect_right(_KeyView(self, page), separator)
            if page.can_fit(len(entry)):
                page.insert_record(entry, at=position)
                return None
            return self._split_internal(page, entry, position)

    def _split_leaf(self, page, entry, position):
        """splits a full leaf in half, keeps the chain linked and copies up the new first key."""
        entries = page.records()
        entries.insert(position, entry)
        middle = len(entries) // 2
        left, right = entries[:middle], entries[middle:]

        with self.pool.allocate(PageType.BTREE_LEAF) as sibling:
            self._fill(sibling, right)
            sibling.next_page_id = page.next_page_id
            sibling.prev_page_id = page.page_id
            sibling_id = sibling.page_id

        if page.next_page_id != NULL_PAGE:
            with self.pool.modify(page.next_page_id) as following:
                following.prev_page_id = sibling_id

        self._fill(page, left)
        page.next_page_id = sibling_id
        return self.unpack_key(right[0]), sibling_id

    def _split_internal(self, page, entry, position):
        """splits a full internal node, pushing the middle key up instead of copying it."""
        entries = page.records()
        entries.insert(position, entry)
        middle = len(entries) // 2
        separator_entry = entries[middle]
        left, right = entries[:middle], entries[middle + 1:]

        with self.pool.allocate(PageType.BTREE_INTERNAL) as sibling:
            sibling.next_page_id = self._internal_child(separator_entry)   # promoted key's right child
            self._fill(sibling, right)
            sibling_id = sibling.page_id

        self._fill(page, left)
        return self.unpack_key(separator_entry), sibling_id

    def _fill(self, page, entries):
        """rewrites a node with exactly the given records, preserving their order."""
        while page.slot_count:
            page.remove_slot(page.slot_count - 1)
        page.compact()
        for position, entry in enumerate(entries):
            page.insert_record(entry, at=position)

    # ---------- delete ----------

    def delete(self, key, rid=None):
        """removes entries for a key (optionally just one RID) without merging nodes."""
        page_id = self._descend(key)
        removed = 0
        while page_id != NULL_PAGE:
            with self.pool.modify(page_id) as page:
                entries = page.records()
                keys = [self.unpack_key(e) for e in entries]
                position = bisect_left(keys, key)
                if position >= len(keys) or keys[position] != key:
                    break
                index = position
                while index < len(keys) and keys[index] == key:
                    if rid is None or self._leaf_rid(entries[index]) == tuple(rid):
                        page.remove_slot(index)
                        entries.pop(index)
                        keys.pop(index)
                        removed += 1
                        if rid is not None:
                            break
                    else:
                        index += 1
                exhausted = bool(keys) and keys[-1] != key
                page_id = NULL_PAGE if (exhausted or rid is not None) else page.next_page_id
        self.num_entries -= removed
        self._span = None
        return removed

    def stats(self):
        """returns the shape of the tree, used by the report to relate block size to height."""
        return {
            "height": self.depth,
            "entries": self.num_entries,
            "fan_out": self.fan_out(),
            "leaf_capacity": self.leaf_capacity(),
            "pages": self.disk.num_pages(),
            "key_type": self.key_type,
        }

    def __repr__(self):
        return f"BPlusTree({self.path!r}, height={self.depth}, entries={self.num_entries}, M={self.fan_out()})"
