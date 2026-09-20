"""Heap File (enunciado 3.2.1).

Unordered records with a free-list of pages that still have room::

    page 0        header: num_records + free_head
    page 1..P     data pages, linked head-first through `next_page_id`

Cost model:
    insert  O(1) I/O   -- pop the free-list head, or append one page
    search  P reads    -- full table scan, no ordering to exploit
    delete  O(1) I/O   -- tombstone the slot (free-list), or move-the-last
"""

from backend.storage import NULL_PAGE, PageType

from .base import PagedFile

HEADER_GUARD = 0  # page 0 is the file header and never holds user records


class HeapFile(PagedFile):
    """stores records in insertion order and finds free space through an on-disk free-list."""

    page_type = PageType.HEAP_DATA

    # ---------- free list ----------

    def _pop_free_page(self):
        """returns the free-list head page id, or NULL_PAGE when no page has room."""
        return self.header.free_head

    def _unlink_head(self, page):
        """removes the current head from the free-list once it can no longer take a record."""
        self.header.free_head = page.next_page_id
        page.next_page_id = NULL_PAGE
        page.in_free_list = False

    def _push_free(self, page):
        """links a page at the front of the free-list so the next insert finds it in O(1)."""
        if page.in_free_list:
            return
        page.next_page_id = self.header.free_head
        page.in_free_list = True
        self.header.free_head = page.page_id

    # ---------- write path ----------

    def insert(self, record):
        """places a record in the first page with room, or in a brand-new page; returns its RID."""
        size = len(record)
        page_id = self._pop_free_page()
        while page_id != NULL_PAGE:
            with self.pool.modify(page_id) as page:
                if page.can_fit(size):
                    slot = page.insert_record(record)
                    if not page.can_fit(size):
                        self._unlink_head(page)
                    self.header.num_records += 1
                    return (page_id, slot)
                self._unlink_head(page)
                page_id = self.header.free_head

        with self.pool.allocate(PageType.HEAP_DATA) as page:
            slot = page.insert_record(record)
            if page.can_fit(size):
                self._push_free(page)
            self.header.num_records += 1
            return (page.page_id, slot)

    def bulk_insert(self, records):
        """inserts many records in one pass, reusing the open page instead of re-walking the free-list."""
        return [self.insert(record) for record in records]

    # ---------- read path ----------

    def get(self, rid):
        """reads one record by RID, costing a single block read."""
        page_id, slot = rid
        if page_id <= HEADER_GUARD or page_id >= self.num_pages:
            return None
        with self.pool.get(page_id) as page:
            return page.get_record(slot)

    def scan(self):
        """full table scan: yields <RID, record> page by page, costing P block reads."""
        for page_id in range(1, self.num_pages):
            with self.pool.get(page_id) as page:
                if page.page_type is not PageType.HEAP_DATA:
                    continue
                for slot, record in page.iter_records():
                    yield (page_id, slot), record

    def search(self, predicate):
        """returns every record matching a predicate, by scanning the whole file."""
        return [(rid, record) for rid, record in self.scan() if predicate(record)]

    # ---------- delete path ----------

    def delete(self, rid, strategy="free_list"):
        """removes a record either by tombstoning its slot or by pulling the last record into the hole."""
        if strategy == "move_last":
            return self._delete_move_last(rid)
        return self._delete_logical(rid)

    def _delete_logical(self, rid):
        """tombstones the slot and puts the page back in the free-list so the space is reused."""
        page_id, slot = rid
        if page_id <= HEADER_GUARD or page_id >= self.num_pages:
            return False
        with self.pool.modify(page_id) as page:
            if not page.delete_record(slot):
                return False
            self._push_free(page)
        self.header.num_records -= 1
        return True

    def _delete_move_last(self, rid):
        """overwrites the deleted record with the file's last one and shrinks the file when a page empties."""
        page_id, slot = rid
        with self.pool.get(page_id) as page:
            if page.get_record(slot) is None:
                return False

        source_id = self._last_non_empty_page()
        if source_id is None:
            return False

        with self.pool.modify(source_id) as source:
            last_slot = max(s for s, _ in source.iter_records())
            if source_id == page_id and last_slot == slot:
                source.delete_record(slot)
                self.header.num_records -= 1
                self._release_trailing_pages()
                return True
            moved = source.get_record(last_slot)
            source.delete_record(last_slot)

        with self.pool.modify(page_id) as target:
            target.replace_record(slot, moved)

        self.header.num_records -= 1
        self._release_trailing_pages()
        return True

    def _last_non_empty_page(self):
        """walks backward from the end of the file to the last page that still holds a record."""
        for page_id in range(self.num_pages - 1, 0, -1):
            with self.pool.get(page_id) as page:
                if page.record_count > 0:
                    return page_id
        return None

    def _release_trailing_pages(self):
        """truncates empty pages at the end of the file and drops them from the free-list and cache."""
        last = self.num_pages - 1
        released = []
        while last >= 1:
            with self.pool.get(last) as page:
                if page.record_count > 0:
                    break
            released.append(last)
            last -= 1
        if not released:
            return
        dropped = set(released)
        self.header.free_head = self._filtered_free_head(dropped)
        for page_id in released:
            self.pool.discard(page_id)
        self.disk.truncate(last + 1)

    def _filtered_free_head(self, dropped):
        """rebuilds the free-list skipping pages that were just truncated away."""
        page_id = self.header.free_head
        while page_id != NULL_PAGE and page_id in dropped:
            with self.pool.get(page_id) as page:
                page_id = page.next_page_id
        head = page_id
        while page_id != NULL_PAGE:
            with self.pool.modify(page_id) as page:
                nxt = page.next_page_id
                while nxt != NULL_PAGE and nxt in dropped:
                    with self.pool.get(nxt) as skipped:
                        nxt = skipped.next_page_id
                page.next_page_id = nxt
                page_id = nxt
        return head

    def __repr__(self):
        return f"HeapFile({self.path!r}, records={self.num_records}, pages={self.num_pages})"

