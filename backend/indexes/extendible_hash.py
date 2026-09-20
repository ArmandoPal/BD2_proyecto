"""Extendible hashing on disk (enunciado 3.3.2).

A directory of ``2^global_depth`` slots, each pointing at a bucket page::

    page 0        header: first directory page, global depth, entry count
    directory     pages of packed u32 bucket ids, chained through next_page_id
    buckets       pages of <key, RID> entries; the local depth lives in the
                  page header's `flags` field

Lookup is one directory hit plus one bucket read, so equality search is O(1)
block transfers regardless of N -- the property the experiments contrast
against the B+ tree.

When a bucket overflows:
    local_depth <  global_depth  ->  split the bucket, repoint half the slots
    local_depth == global_depth  ->  double the directory first, then split

If every key in a bucket hashes to the same suffix, splitting cannot separate
them; the bucket then chains an overflow page, which keeps the structure
correct instead of looping forever.
"""

import struct
import zlib

from backend.catalog.record import RID_SIZE, pack_rid, unpack_rid
from backend.storage import NULL_PAGE, PageType

from .base import IndexFile

SLOT_FORMAT = "<I"
DIR_SLOT_SIZE = struct.calcsize(SLOT_FORMAT)
MAX_GLOBAL_DEPTH = 20


class ExtendibleHash(IndexFile):
    """hash index whose directory doubles on demand so buckets never chain unnecessarily."""

    def __init__(self, path, key_type, page_size=4096, counter=None, capacity=64):
        """opens the index and loads the directory, creating a one-bucket directory if new."""
        super().__init__(path, key_type, page_size=page_size, counter=counter, capacity=capacity)
        self.directory = self._load_directory()
        if not self.directory:
            self._bootstrap()

    # ---------- hashing ----------

    def _hash(self, key):
        """stable hash of a packed key; crc32 is used so the value survives a restart."""
        return zlib.crc32(self.pack_key(key))

    def _slot_of(self, key):
        """keeps the lowest `global_depth` bits of the hash, which is the directory index."""
        return self._hash(key) & ((1 << self.depth) - 1)

    # ---------- directory persistence ----------

    def _slots_per_page(self):
        """how many u32 bucket pointers fit in one directory page."""
        from backend.storage import HEADER_SIZE, SLOT_SIZE
        return (self.page_size - HEADER_SIZE - SLOT_SIZE) // DIR_SLOT_SIZE

    def _load_directory(self):
        """reads the chained directory pages back into an in-memory list of bucket ids."""
        entries, page_id = [], self.root_page_id
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as page:
                raw = page.get_record(0) or b""
                entries.extend(struct.unpack(f"<{len(raw) // DIR_SLOT_SIZE}I", raw))
                page_id = page.next_page_id
        return entries[:1 << self.depth]

    def _store_directory(self):
        """rewrites the whole directory, allocating or reusing as many pages as it now needs."""
        per_page = self._slots_per_page()
        chunks = [self.directory[i:i + per_page] for i in range(0, len(self.directory), per_page)] or [[]]

        page_ids, page_id = [], self.root_page_id
        while page_id != NULL_PAGE and len(page_ids) < len(chunks):
            page_ids.append(page_id)
            with self.pool.get(page_id) as page:
                page_id = page.next_page_id
        while len(page_ids) < len(chunks):
            with self.pool.allocate(PageType.DIRECTORY) as page:
                page_ids.append(page.page_id)

        for position, (page_id, chunk) in enumerate(zip(page_ids, chunks)):
            payload = struct.pack(f"<{len(chunk)}I", *chunk)
            with self.pool.modify(page_id) as page:
                if page.get_record(0) is None:
                    page.insert_record(payload)
                else:
                    page.replace_record(0, payload)
                page.next_page_id = page_ids[position + 1] if position + 1 < len(page_ids) else NULL_PAGE
        self.root_page_id = page_ids[0]

    def _bootstrap(self):
        """creates the initial directory: global depth 0 and a single empty bucket."""
        with self.pool.allocate(PageType.HASH_BUCKET) as bucket:
            bucket.flags = 0                     # local depth 0
            bucket_id = bucket.page_id
        self.depth = 0
        self.directory = [bucket_id]
        self._store_directory()

    # ---------- entries ----------

    def _entry(self, key, rid):
        """builds a bucket record: the packed key followed by its 6-byte RID."""
        return self.pack_key(key) + pack_rid(rid)

    def _entry_rid(self, entry):
        """reads the RID out of a bucket record."""
        return unpack_rid(entry[self.key_size:self.key_size + RID_SIZE])

    def bucket_capacity(self):
        """maximum number of <key, RID> pairs one bucket page can hold."""
        from backend.storage import HEADER_SIZE, SLOT_SIZE
        return (self.page_size - HEADER_SIZE) // (self.leaf_entry_size + SLOT_SIZE)

    # ---------- search ----------

    def search(self, key):
        """hashes the key to one directory slot, reads that bucket and walks its overflow chain."""
        page_id = self.directory[self._slot_of(key)]
        found = []
        while page_id != NULL_PAGE:
            with self.pool.get(page_id) as bucket:
                for entry in bucket.records():
                    if self.unpack_key(entry) == key:
                        found.append(self._entry_rid(entry))
                page_id = bucket.next_page_id
        return found

    def scan(self):
        """yields every <key, RID> pair; order is hash order, not key order."""
        seen = set()
        for bucket_id in self.directory:
            page_id = bucket_id
            while page_id != NULL_PAGE and page_id not in seen:
                seen.add(page_id)
                with self.pool.get(page_id) as bucket:
                    for entry in bucket.records():
                        yield self.unpack_key(entry), self._entry_rid(entry)
                    page_id = bucket.next_page_id

    # ---------- insert ----------

    def insert(self, key, rid):
        """places an entry in its bucket, splitting the bucket or doubling the directory if it is full."""
        entry = self._entry(key, rid)
        for _ in range(MAX_GLOBAL_DEPTH + 1):
            slot = self._slot_of(key)
            bucket_id = self.directory[slot]
            with self.pool.modify(bucket_id) as bucket:
                if bucket.can_fit(len(entry)):
                    bucket.insert_record(entry)
                    self.num_entries += 1
                    return
                local_depth = bucket.flags
            if local_depth >= MAX_GLOBAL_DEPTH:
                break
            if local_depth == self.depth:
                self._double_directory()
            self._split_bucket(slot)
        self._chain_overflow(self.directory[self._slot_of(key)], entry)
        self.num_entries += 1

    def _double_directory(self):
        """duplicates every directory slot so the new bit can distinguish two buckets."""
        if self.depth >= MAX_GLOBAL_DEPTH:
            raise RuntimeError("extendible hashing reached its maximum global depth")
        self.directory = self.directory + list(self.directory)
        self.depth += 1
        self._store_directory()

    def _split_bucket(self, slot):
        """splits one bucket in two by the next hash bit and repoints the slots that now differ."""
        old_id = self.directory[slot]
        with self.pool.modify(old_id) as bucket:
            local_depth = bucket.flags + 1
            entries = bucket.records()
            bucket.flags = local_depth
            self._clear(bucket)

        with self.pool.allocate(PageType.HASH_BUCKET) as sibling:
            sibling.flags = local_depth
            new_id = sibling.page_id

        bit = 1 << (local_depth - 1)
        for index in range(len(self.directory)):
            if self.directory[index] == old_id and index & bit:
                self.directory[index] = new_id
        self._store_directory()

        for entry in entries:
            target = new_id if self._hash(self.unpack_key(entry)) & bit else old_id
            with self.pool.modify(target) as bucket:
                if bucket.can_fit(len(entry)):
                    bucket.insert_record(entry)
                    continue
            self._chain_overflow(target, entry)

    def _chain_overflow(self, bucket_id, entry):
        """appends an overflow page to a bucket whose keys cannot be separated by more bits."""
        page_id = bucket_id
        while True:
            with self.pool.modify(page_id) as bucket:
                if bucket.can_fit(len(entry)):
                    bucket.insert_record(entry)
                    return
                if bucket.next_page_id != NULL_PAGE:
                    page_id = bucket.next_page_id
                    continue
                local_depth = bucket.flags
            with self.pool.allocate(PageType.HASH_BUCKET) as overflow:
                overflow.flags = local_depth
                overflow.insert_record(entry)
                overflow_id = overflow.page_id
            with self.pool.modify(page_id) as bucket:
                bucket.next_page_id = overflow_id
            return

    def _clear(self, page):
        """empties a bucket page while keeping its header fields intact."""
        while page.slot_count:
            page.remove_slot(page.slot_count - 1)
        page.compact()

    # ---------- delete ----------

    def delete(self, key, rid=None):
        """removes entries for a key from its bucket chain; buckets are never merged back."""
        page_id = self.directory[self._slot_of(key)]
        removed = 0
        while page_id != NULL_PAGE:
            with self.pool.modify(page_id) as bucket:
                for index in range(bucket.slot_count - 1, -1, -1):
                    entry = bucket.get_record(index)
                    if entry is None or self.unpack_key(entry) != key:
                        continue
                    if rid is None or self._entry_rid(entry) == tuple(rid):
                        bucket.remove_slot(index)
                        removed += 1
                        if rid is not None:
                            self.num_entries -= removed
                            return removed
                page_id = bucket.next_page_id
        self.num_entries -= removed
        return removed

    # ---------- reporting ----------

    def flush(self):
        """persists the directory alongside the header and the dirty buckets."""
        self._store_directory()
        super().flush()

    def stats(self):
        """returns directory and bucket shape, used to explain O(1) lookups in the report."""
        return {
            "global_depth": self.depth,
            "directory_slots": len(self.directory),
            "buckets": len(set(self.directory)),
            "entries": self.num_entries,
            "bucket_capacity": self.bucket_capacity(),
            "pages": self.disk.num_pages(),
            "key_type": self.key_type,
        }

    def __repr__(self):
        return (f"ExtendibleHash({self.path!r}, global_depth={self.depth}, "
                f"buckets={len(set(self.directory))}, entries={self.num_entries})")
