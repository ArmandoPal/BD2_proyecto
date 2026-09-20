"""Slotted-page layout for fixed-size binary blocks.

Byte map of a page::

    [0, HEADER_SIZE)                  page header (struct-packed)
    [HEADER_SIZE, free_space_offset)  record bytes, growing forward
    [free_space_offset, dir_start)    free gap
    [dir_start, page_size)            slot directory, growing backward

A slot is ``<offset, length>``; ``<0, 0>`` marks a tombstone (deleted record).
A tuple is addressed by ``RID = <page_id, slot>``.
"""

import struct
from enum import IntEnum

DEFAULT_PAGE_SIZE = 4096
VALID_PAGE_SIZES = (1024, 2048, 4096, 8192)

# page_id, slot_count, record_count, free_space_offset, flags, next, prev, type
HEADER_FORMAT = "<IHHHHiiB3x"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

SLOT_FORMAT = "<HH"
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)

NULL_PAGE = -1
TOMBSTONE = (0, 0)

FLAG_IN_FREE_LIST = 1 << 0


class PageType(IntEnum):
    FREE = 0
    FILE_HEADER = 1
    HEAP_DATA = 2
    SEQ_MAIN = 3
    SEQ_OVERFLOW = 4
    BTREE_INTERNAL = 5
    BTREE_LEAF = 6
    HASH_BUCKET = 7
    CATALOG = 8
    DIRECTORY = 9


class PageFullError(Exception):
    """raised when a record cannot fit in a page even after compaction."""


class Page:
    """in-memory image of one disk block; all mutations happen here, never on disk."""

    __slots__ = (
        "page_id", "page_size", "page_type", "slot_count", "record_count",
        "free_space_offset", "flags", "next_page_id", "prev_page_id", "data",
    )

    def __init__(self, page_id, page_size=DEFAULT_PAGE_SIZE, page_type=PageType.HEAP_DATA):
        """builds a blank page with an empty record area and an empty slot directory."""
        if page_size not in VALID_PAGE_SIZES:
            raise ValueError(f"page_size must be one of {VALID_PAGE_SIZES}, got {page_size}")
        self.page_id = page_id
        self.page_size = page_size
        self.page_type = PageType(page_type)
        self.slot_count = 0
        self.record_count = 0
        self.free_space_offset = HEADER_SIZE
        self.flags = 0
        self.next_page_id = NULL_PAGE
        self.prev_page_id = NULL_PAGE
        self.data = bytearray(page_size)

    # ---------- serialization ----------

    @classmethod
    def from_bytes(cls, raw, page_size=None):
        """rebuilds a page from a raw block by unpacking its header and keeping the bytes as-is."""
        size = page_size or len(raw)
        if len(raw) != size:
            raise ValueError(f"expected {size} bytes, got {len(raw)}")
        fields = struct.unpack_from(HEADER_FORMAT, raw, 0)
        page = cls.__new__(cls)
        page.page_size = size
        (page.page_id, page.slot_count, page.record_count, page.free_space_offset,
         page.flags, page.next_page_id, page.prev_page_id, page_type) = fields
        page.page_type = PageType(page_type)
        page.data = bytearray(raw)
        return page

    def to_bytes(self):
        """writes the header back into the byte buffer and returns the full block."""
        struct.pack_into(
            HEADER_FORMAT, self.data, 0,
            self.page_id, self.slot_count, self.record_count, self.free_space_offset,
            self.flags, self.next_page_id, self.prev_page_id, int(self.page_type),
        )
        return bytes(self.data)

    # ---------- slot directory ----------

    def _slot_pos(self, index):
        """maps a slot index to its byte offset, counting backward from the end of the page."""
        return self.page_size - (index + 1) * SLOT_SIZE

    def _read_slot(self, index):
        """unpacks the <offset, length> pair stored at a slot index."""
        return struct.unpack_from(SLOT_FORMAT, self.data, self._slot_pos(index))

    def _write_slot(self, index, offset, length):
        """packs an <offset, length> pair into a slot index."""
        struct.pack_into(SLOT_FORMAT, self.data, self._slot_pos(index), offset, length)

    @property
    def dir_start(self):
        """byte offset where the slot directory begins (it grows toward lower addresses)."""
        return self.page_size - self.slot_count * SLOT_SIZE

    @property
    def free_space(self):
        """contiguous bytes between the end of the records and the start of the directory."""
        return self.dir_start - self.free_space_offset

    @property
    def used_bytes(self):
        """sum of the lengths of the live records, ignoring fragmentation holes."""
        return sum(length for _, length in self._live_slots())

    def _live_slots(self):
        """yields <offset, length> for every slot that is not a tombstone."""
        for i in range(self.slot_count):
            offset, length = self._read_slot(i)
            if (offset, length) != TOMBSTONE:
                yield offset, length

    def _find_tombstone(self):
        """returns the first reusable slot index, or None when the directory has no holes."""
        for i in range(self.slot_count):
            if self._read_slot(i) == TOMBSTONE:
                return i
        return None

    # ---------- records ----------

    def can_fit(self, length):
        """true when a record of the given length fits, counting compaction as available space."""
        reclaimable = self.free_space_offset - HEADER_SIZE - self.used_bytes
        needed = length + (0 if self._find_tombstone() is not None else SLOT_SIZE)
        return self.free_space + reclaimable >= needed

    def insert_record(self, record, at=None):
        """appends record bytes and returns its slot; reuses a tombstone, or inserts the slot at `at` to keep key order."""
        length = len(record)
        if length == 0 or length > self.page_size:
            raise ValueError("record length out of range")

        reuse = self._find_tombstone() if at is None else None
        extra_slot = 0 if reuse is not None else SLOT_SIZE

        if self.free_space < length + extra_slot:
            if not self.can_fit(length):
                raise PageFullError(f"page {self.page_id} cannot fit {length} bytes")
            self.compact()
            reuse = self._find_tombstone() if at is None else None
            extra_slot = 0 if reuse is not None else SLOT_SIZE
            if self.free_space < length + extra_slot:
                raise PageFullError(f"page {self.page_id} cannot fit {length} bytes")

        offset = self.free_space_offset
        self.data[offset:offset + length] = record
        self.free_space_offset += length

        if reuse is not None:
            slot = reuse
        else:
            slot = self.slot_count if at is None else at
            if at is not None:
                self._shift_slots_right(at)
            self.slot_count += 1

        self._write_slot(slot, offset, length)
        self.record_count += 1
        return slot

    def _shift_slots_right(self, index):
        """moves directory entries from `index` onward one position down to open a gap."""
        for i in range(self.slot_count, index, -1):
            offset, length = self._read_slot(i - 1)
            self._write_slot(i, offset, length)

    def get_record(self, slot):
        """returns the raw bytes of a slot, or None when the slot is out of range or deleted."""
        if slot < 0 or slot >= self.slot_count:
            return None
        offset, length = self._read_slot(slot)
        if (offset, length) == TOMBSTONE:
            return None
        return bytes(self.data[offset:offset + length])

    def delete_record(self, slot):
        """logically deletes a record by zeroing its slot; the bytes are reclaimed on compaction."""
        if self.get_record(slot) is None:
            return False
        self._write_slot(slot, *TOMBSTONE)
        self.record_count -= 1
        return True

    def remove_slot(self, index):
        """drops a directory entry and shifts the rest up, used by ordered pages where slots are positions."""
        if index < 0 or index >= self.slot_count:
            return False
        live = self._read_slot(index) != TOMBSTONE
        for i in range(index, self.slot_count - 1):
            offset, length = self._read_slot(i + 1)
            self._write_slot(i, offset, length)
        self._write_slot(self.slot_count - 1, *TOMBSTONE)
        self.slot_count -= 1
        if live:
            self.record_count -= 1
        return True

    def replace_record(self, slot, record):
        """overwrites a record in place when the size matches, otherwise re-inserts it at the same slot."""
        offset, length = self._read_slot(slot)
        if length == len(record):
            self.data[offset:offset + length] = record
            return slot
        self._write_slot(slot, *TOMBSTONE)
        self.record_count -= 1
        if self.free_space < len(record):
            self.compact()
        new_offset = self.free_space_offset
        self.data[new_offset:new_offset + len(record)] = record
        self.free_space_offset += len(record)
        self._write_slot(slot, new_offset, len(record))
        self.record_count += 1
        return slot

    def iter_records(self):
        """yields <slot, bytes> for every live record, skipping tombstones."""
        for i in range(self.slot_count):
            offset, length = self._read_slot(i)
            if (offset, length) != TOMBSTONE:
                yield i, bytes(self.data[offset:offset + length])

    def records(self):
        """returns the live record bytes in slot order, which is key order on ordered pages."""
        return [record for _, record in self.iter_records()]

    def compact(self):
        """repacks live records against the header to reclaim holes left by deletes and updates."""
        cursor = HEADER_SIZE
        packed = bytearray(self.page_size)
        packed[:HEADER_SIZE] = self.data[:HEADER_SIZE]
        packed[self.dir_start:] = self.data[self.dir_start:]
        for i in range(self.slot_count):
            offset, length = self._read_slot(i)
            if (offset, length) == TOMBSTONE:
                continue
            packed[cursor:cursor + length] = self.data[offset:offset + length]
            struct.pack_into(SLOT_FORMAT, packed, self._slot_pos(i), cursor, length)
            cursor += length
        self.data = packed
        self.free_space_offset = cursor

    # ---------- free-list bookkeeping ----------

    @property
    def in_free_list(self):
        """true when this page is currently linked in its file's free-list."""
        return bool(self.flags & FLAG_IN_FREE_LIST)

    @in_free_list.setter
    def in_free_list(self, value):
        """sets or clears the free-list membership bit in the page header."""
        if value:
            self.flags |= FLAG_IN_FREE_LIST
        else:
            self.flags &= ~FLAG_IN_FREE_LIST

    def __repr__(self):
        return (f"Page(id={self.page_id}, type={self.page_type.name}, "
                f"records={self.record_count}, slots={self.slot_count}, free={self.free_space})")
