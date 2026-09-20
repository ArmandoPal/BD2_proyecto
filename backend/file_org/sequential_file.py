"""Sequential File with overflow area (enunciado 3.2.2).

Two binary files kept in sync::

    <name>.dat   page 0 header, then main pages physically sorted by key
    <name>.ovf   overflow pages, chained from the main page they belong to

Each main page points at the head of its own overflow chain through
``next_page_id``. The main area supports binary search (log2 M reads); records
that no longer fit land in the chain, so every insert past a full page slowly
degrades search until ``reorganize()`` merges both areas back into a clean,
sorted main file with a 70-80% fill factor.

A record is addressed by ``Location = (area, page_id, slot)`` where area is
``"main"`` or ``"overflow"``, because the two areas are different files.
"""

import os
from bisect import bisect_left, bisect_right

from backend.storage import BufferPool, DiskManager, NULL_PAGE, Page, PageType

from .base import HEADER_PAGE, FileHeader, PagedFile

MAIN = "main"
OVERFLOW = "overflow"
MIN_FILL_FACTOR = 0.70
MAX_FILL_FACTOR = 0.80


class SequentialFile(PagedFile):
    """keeps records sorted by key in the main area and pushes the rest into chained overflow pages."""

    page_type = PageType.SEQ_MAIN

    def __init__(self, path, schema, key_column, page_size=4096, counter=None,
                 capacity=64, fill_factor=0.75):
        """opens the main file plus its overflow companion, both sharing one I/O counter."""
        super().__init__(path, schema, page_size=page_size, counter=counter, capacity=capacity)
        self.key_column = key_column
        self.key_type = schema.column(key_column).dtype
        self.fill_factor = min(max(fill_factor, MIN_FILL_FACTOR), MAX_FILL_FACTOR)
        self.overflow_path = self._overflow_path(path)
        self.overflow_disk = DiskManager(self.overflow_path, page_size=page_size, counter=self.counter)
        self.overflow_pool = BufferPool(self.overflow_disk, capacity=capacity)
        self._init_overflow()

    @staticmethod
    def _overflow_path(path):
        """derives the overflow file name from the main one, keeping them side by side."""
        root, _ = os.path.splitext(path)
        return root + ".ovf"

    def _init_overflow(self):
        """makes sure the overflow file has its header page before anything is chained into it."""
        if self.overflow_disk.num_pages() == 0:
            self.overflow_disk.allocate_page(PageType.FILE_HEADER)

    # ---------- keys ----------

    def _key(self, record):
        """extracts the indexed key out of a packed record."""
        return self.schema.key_of(record, self.key_column)

    def _keys_of(self, page):
        """returns the keys of a page in slot order, which is key order on a sorted page."""
        return [self._key(record) for record in page.records()]

    # ---------- main area navigation ----------

    @property
    def num_main_pages(self):
        """number of sorted data pages in the main file, header page excluded."""
        return max(0, self.disk.num_pages() - 1)

    def _first_key(self, page_id):
        """returns the smallest key stored in a main page, or None when the page is empty."""
        with self.pool.get(page_id) as page:
            records = page.records()
            return self._key(records[0]) if records else None

    def _find_page(self, key):
        """binary searches the sorted main pages for the one whose key range contains `key`."""
        lo, hi = 1, self.num_main_pages
        target = 1
        while lo <= hi:
            mid = (lo + hi) // 2
            first = self._first_key(mid)
            if first is None:                      # emptied by deletes: probe to the right
                probe = mid + 1
                while probe <= hi and first is None:
                    first = self._first_key(probe)
                    probe += 1
                if first is None:
                    hi = mid - 1
                    continue
            if first <= key:
                target = mid
                lo = mid + 1
            else:
                hi = mid - 1
        return target

    # ---------- write path ----------

    def insert(self, record):
        """inserts in sorted position in the target main page, or chains the record into overflow."""
        key = self._key(record)
        size = len(record)

        if self.num_main_pages == 0:
            with self.pool.allocate(PageType.SEQ_MAIN) as page:
                page.insert_record(record, at=0)
                self.header.num_records += 1
                return (MAIN, page.page_id, 0)

        page_id = self._find_page(key)
        with self.pool.modify(page_id) as page:
            if page.can_fit(size):
                position = bisect_right(self._keys_of(page), key)
                slot = page.insert_record(record, at=position)
                self.header.num_records += 1
                return (MAIN, page_id, slot)
            appendable = self._appends_at_end(page, page_id, key)
            chain_head = page.next_page_id

        if appendable:
            with self.pool.allocate(PageType.SEQ_MAIN) as page:
                page.insert_record(record, at=0)
                self.header.num_records += 1
                return (MAIN, page.page_id, 0)

        location = self._insert_overflow(chain_head, record, key, size)
        if location[1] != chain_head:
            with self.pool.modify(page_id) as page:
                page.next_page_id = location[1]
        self.header.num_records += 1
        return location

    def _appends_at_end(self, page, page_id, key):
        """true when a full last page gets a key above its maximum, so the main area can simply grow."""
        if page_id != self.num_main_pages:
            return False
        keys = self._keys_of(page)
        return bool(keys) and key >= keys[-1]

    def _insert_overflow(self, chain_head, record, key, size):
        """walks the chain for a page with room, otherwise pushes a new page at the chain head."""
        page_id = chain_head
        while page_id != NULL_PAGE:
            with self.overflow_pool.modify(page_id) as page:
                if page.can_fit(size):
                    position = bisect_right(self._keys_of(page), key)
                    slot = page.insert_record(record, at=position)
                    return (OVERFLOW, page_id, slot)
                page_id = page.next_page_id

        with self.overflow_pool.allocate(PageType.SEQ_OVERFLOW) as page:
            page.next_page_id = chain_head
            slot = page.insert_record(record, at=0)
            return (OVERFLOW, page.page_id, slot)

    def bulk_insert(self, records):
        """inserts many records; feeding them already sorted keeps the overflow area empty."""
        return [self.insert(record) for record in records]

    # ---------- read path ----------

    def get(self, location):
        """reads one record by its (area, page_id, slot) location."""
        area, page_id, slot = location
        pool = self.pool if area == MAIN else self.overflow_pool
        with pool.get(page_id) as page:
            return page.get_record(slot)

    def _chain_records(self, chain_head):
        """yields every <location, record> hanging off one main page's overflow chain."""
        page_id = chain_head
        while page_id != NULL_PAGE:
            with self.overflow_pool.get(page_id) as page:
                for slot, record in page.iter_records():
                    yield (OVERFLOW, page_id, slot), record
                page_id = page.next_page_id

    def _page_bucket(self, page_id):
        """returns a main page and its whole chain merged and sorted, i.e. one logical bucket."""
        entries = []
        with self.pool.get(page_id) as page:
            for slot, record in page.iter_records():
                entries.append(((MAIN, page_id, slot), record))
            chain_head = page.next_page_id
        entries.extend(self._chain_records(chain_head))
        entries.sort(key=lambda item: self._key(item[1]))
        return entries

    def search(self, key):
        """binary searches to the right page, then scans it and its chain for exact key matches."""
        if self.num_main_pages == 0:
            return []
        page_id = self._find_page(key)
        return [(loc, record) for loc, record in self._page_bucket(page_id)
                if self._key(record) == key]

    def range_search(self, low, high):
        """starts at the page holding `low` and walks forward while page keys stay under `high`."""
        if self.num_main_pages == 0 or low > high:
            return []
        found = []
        for page_id in range(self._find_page(low), self.num_main_pages + 1):
            first = self._first_key(page_id)
            if first is not None and first > high:
                break
            for location, record in self._page_bucket(page_id):
                key = self._key(record)
                if low <= key <= high:
                    found.append((location, record))
        return found

    def scan(self):
        """yields every record in key order by merging each main page with its overflow chain."""
        for page_id in range(1, self.num_main_pages + 1):
            yield from self._page_bucket(page_id)

    # ---------- delete path ----------

    def delete(self, key):
        """logically deletes every record with the given key, in the main area and in overflow."""
        removed = 0
        for area, page_id, slot in sorted((loc for loc, _ in self.search(key)), reverse=True):
            pool = self.pool if area == MAIN else self.overflow_pool
            with pool.modify(page_id) as page:
                if page.remove_slot(slot):
                    removed += 1
        self.header.num_records -= removed
        return removed

    # ---------- maintenance ----------

    def reorganize(self):
        """merges main and overflow in key order into a fresh main file filled to the fill factor."""
        per_page = max(1, int(self.records_per_page() * self.fill_factor))
        tmp_path = self.path + ".reorg"
        stats = {"records": 0, "pages": 0, "fill_factor": self.fill_factor}

        tmp = DiskManager(tmp_path, page_size=self.page_size, counter=self.counter)
        tmp.allocate_page(PageType.FILE_HEADER)

        buffer, total = [], 0
        for _, record in self.scan():
            buffer.append(record)
            total += 1
            if len(buffer) == per_page:
                self._flush_reorg_page(tmp, buffer)
                stats["pages"] += 1
                buffer = []
        if buffer:
            self._flush_reorg_page(tmp, buffer)
            stats["pages"] += 1

        header = FileHeader(num_records=total, num_main_pages=stats["pages"])
        self._write_header_page(tmp, header)
        tmp.close()

        self.pool.flush_all()
        self.disk.close()
        os.replace(tmp_path, self.path)

        self.disk = DiskManager(self.path, page_size=self.page_size, counter=self.counter)
        self.pool = BufferPool(self.disk, capacity=self.pool.capacity)
        self.header = header
        self._reset_overflow()

        stats["records"] = total
        return stats

    def _flush_reorg_page(self, disk, records):
        """writes one freshly filled, sorted page into the file being rebuilt."""
        page_id = disk.allocate_page(PageType.SEQ_MAIN)
        page = Page(page_id, self.page_size, PageType.SEQ_MAIN)
        for position, record in enumerate(records):
            page.insert_record(record, at=position)
        disk.write_page(page_id, page.to_bytes())

    def _write_header_page(self, disk, header):
        """stamps the rebuilt file's page 0 with the new record and page counts."""
        page = Page(HEADER_PAGE, self.page_size, PageType.FILE_HEADER)
        page.insert_record(header.pack())
        disk.write_page(HEADER_PAGE, page.to_bytes())

    def _reset_overflow(self):
        """empties the overflow file back to a single header page after a reorganization."""
        for page_id in range(self.overflow_disk.num_pages()):
            self.overflow_pool.discard(page_id)
        self.overflow_disk.truncate(0)
        self.overflow_disk.allocate_page(PageType.FILE_HEADER)

    def overflow_pages(self):
        """counts the overflow blocks in use, the number that tells you when to reorganize."""
        return max(0, self.overflow_disk.num_pages() - 1)

    # ---------- lifecycle ----------

    def flush(self):
        """writes the header and both files' dirty pages back to disk."""
        self.header.num_main_pages = self.num_main_pages
        super().flush()
        self.overflow_pool.flush_all()

    def close(self):
        """flushes and closes the main and overflow files."""
        self.flush()
        self.disk.close()
        self.overflow_disk.close()

    def __repr__(self):
        return (f"SequentialFile({self.path!r}, key={self.key_column}, "
                f"records={self.num_records}, main_pages={self.num_main_pages}, "
                f"overflow_pages={self.overflow_pages()})")
