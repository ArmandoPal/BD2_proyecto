"""Shared plumbing for the file organizations (enunciado 3.2).

Both a heap file and a sequential file are a binary file whose page 0 is a
header block and whose remaining pages hold records. The header is kept in RAM
while the file is open and written back on ``flush()``/``close()`` -- the same
trick a real engine uses, and it keeps the measured I/O of a scan equal to the
number of data pages, which is what the cost formulas predict.
"""

import struct

from backend.storage import BufferPool, DiskManager, NULL_PAGE, Page, PageType

HEADER_PAGE = 0
HEADER_RECORD_FORMAT = "<QqqI"  # num_records, free_head, overflow_head, num_main_pages
HEADER_RECORD_SIZE = struct.calcsize(HEADER_RECORD_FORMAT)


class FileHeader:
    """in-memory image of page 0: record count and the file's structural pointers."""

    __slots__ = ("num_records", "free_head", "overflow_head", "num_main_pages")

    def __init__(self, num_records=0, free_head=NULL_PAGE, overflow_head=NULL_PAGE, num_main_pages=0):
        """starts an empty header whose pointers are all null."""
        self.num_records = num_records
        self.free_head = free_head
        self.overflow_head = overflow_head
        self.num_main_pages = num_main_pages

    def pack(self):
        """packs the four header fields into a single fixed-size record."""
        return struct.pack(HEADER_RECORD_FORMAT, self.num_records, self.free_head,
                           self.overflow_head, self.num_main_pages)

    @classmethod
    def unpack(cls, raw):
        """rebuilds a header from the record written by pack()."""
        return cls(*struct.unpack(HEADER_RECORD_FORMAT, raw))


class PagedFile:
    """owns one binary file plus its buffer pool, and persists a small header in page 0."""

    page_type = PageType.HEAP_DATA

    def __init__(self, path, schema, page_size=4096, counter=None, capacity=64):
        """opens or creates the file, then loads page 0 into the in-memory header."""
        self.path = path
        self.schema = schema
        self.disk = DiskManager(path, page_size=page_size, counter=counter)
        self.pool = BufferPool(self.disk, capacity=capacity)
        self.header = self._load_header()

    # ---------- header ----------

    def _load_header(self):
        """reads page 0 on open, creating it the first time the file is used."""
        if self.disk.num_pages() == 0:
            self.disk.allocate_page(PageType.FILE_HEADER)
            page = Page.from_bytes(self.disk.read_page(HEADER_PAGE), self.page_size)
            page.insert_record(FileHeader().pack())
            self.disk.write_page(HEADER_PAGE, page.to_bytes())
            return FileHeader()
        page = Page.from_bytes(self.disk.read_page(HEADER_PAGE), self.page_size)
        raw = page.get_record(0)
        return FileHeader.unpack(raw) if raw else FileHeader()

    def _save_header(self):
        """writes the in-memory header back into page 0."""
        page = Page.from_bytes(self.disk.read_page(HEADER_PAGE), self.page_size)
        if page.get_record(0) is None:
            page.insert_record(self.header.pack())
        else:
            page.replace_record(0, self.header.pack())
        self.disk.write_page(HEADER_PAGE, page.to_bytes())

    # ---------- shared accessors ----------

    @property
    def page_size(self):
        """block size of this file."""
        return self.disk.page_size

    @property
    def counter(self):
        """the shared I/O counter, so callers can read disk_reads/disk_writes."""
        return self.disk.counter

    @property
    def num_records(self):
        """how many live records the file holds."""
        return self.header.num_records

    @property
    def num_pages(self):
        """total blocks in the file, header page included."""
        return self.disk.num_pages()

    @property
    def num_data_pages(self):
        """blocks that actually hold records, i.e. everything but page 0."""
        return max(0, self.num_pages - 1)

    def records_per_page(self):
        """blocking factor: how many records of this schema fit in one block."""
        from backend.storage import HEADER_SIZE, SLOT_SIZE
        return self.schema.records_per_page(self.page_size, HEADER_SIZE, SLOT_SIZE)

    def flush(self):
        """writes the header and every dirty page back to disk."""
        self._save_header()
        self.pool.flush_all()

    def close(self):
        """flushes and releases the file handle."""
        self.flush()
        self.disk.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
