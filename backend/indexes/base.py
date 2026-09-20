"""Shared plumbing for the on-disk indexes (enunciado 3.3).

An index is its own binary file: page 0 is a header block, the rest are nodes
or buckets. The header is kept in RAM while the file is open and written back
on ``flush()``, so the I/O a lookup reports is only the nodes it actually
walked.

The three header fields mean different things per structure:

=============  ======================  ==========================
field          B+ tree                 extendible hashing
=============  ======================  ==========================
root_page_id   root node               first directory page
depth          height of the tree      global depth
num_entries    <key, RID> pairs        <key, RID> pairs
=============  ======================  ==========================
"""

import struct

from backend.catalog.record import RID_SIZE, type_size, value_codec
from backend.storage import BufferPool, DiskManager, NULL_PAGE, Page, PageType

HEADER_PAGE = 0
INDEX_HEADER_FORMAT = "<iIQ"  # root_page_id, depth, num_entries
INDEX_HEADER_SIZE = struct.calcsize(INDEX_HEADER_FORMAT)


class IndexFile:
    """base class owning an index file, its buffer pool and its persisted header."""

    def __init__(self, path, key_type, page_size=4096, counter=None, capacity=64):
        """opens the index file and derives the entry layout from the key type."""
        self.path = path
        self.key_type = key_type
        self.key_size = type_size(key_type)
        self._key_struct, self._key_to_storage, self._key_from_storage = value_codec(key_type)
        self.disk = DiskManager(path, page_size=page_size, counter=counter)
        self.pool = BufferPool(self.disk, capacity=capacity)
        self.root_page_id, self.depth, self.num_entries = self._load_header()

    # ---------- header ----------

    def _load_header(self):
        """reads page 0, creating it the first time the index is opened."""
        if self.disk.num_pages() == 0:
            self.disk.allocate_page(PageType.FILE_HEADER)
            self._store_header(NULL_PAGE, 0, 0)
            return NULL_PAGE, 0, 0
        page = Page.from_bytes(self.disk.read_page(HEADER_PAGE), self.page_size)
        raw = page.get_record(0)
        return struct.unpack(INDEX_HEADER_FORMAT, raw) if raw else (NULL_PAGE, 0, 0)

    def _store_header(self, root_page_id, depth, num_entries):
        """writes the three header fields into page 0."""
        page = Page.from_bytes(self.disk.read_page(HEADER_PAGE), self.page_size)
        payload = struct.pack(INDEX_HEADER_FORMAT, root_page_id, depth, num_entries)
        if page.get_record(0) is None:
            page.insert_record(payload)
        else:
            page.replace_record(0, payload)
        self.disk.write_page(HEADER_PAGE, page.to_bytes())

    # ---------- keys ----------

    def pack_key(self, key):
        """packs a key value into the fixed-width prefix of an index entry."""
        return self._key_struct.pack(self._key_to_storage(key))

    def unpack_key(self, raw):
        """unpacks the key prefix of an index entry, using the codec compiled when the index was opened."""
        return self._key_from_storage(self._key_struct.unpack(raw[:self.key_size])[0])

    @property
    def page_size(self):
        """block size of the index file."""
        return self.disk.page_size

    @property
    def counter(self):
        """the shared I/O counter."""
        return self.disk.counter

    @property
    def leaf_entry_size(self):
        """bytes taken by one <key, RID> pair."""
        return self.key_size + RID_SIZE

    def height(self):
        """number of block transfers a point lookup costs, i.e. the depth of the structure."""
        return self.depth

    # ---------- lifecycle ----------

    def flush(self):
        """persists the header and every dirty node."""
        self.pool.flush_all()
        self._store_header(self.root_page_id, self.depth, self.num_entries)

    def close(self):
        """flushes and closes the index file."""
        self.flush()
        self.disk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __len__(self):
        return self.num_entries
