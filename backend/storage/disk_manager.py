"""Block-level disk access (enunciado 3.1).

Sole owner of the binary file handle: every read and write is a whole block at
``page_id * page_size``, reached with ``seek``. No pickle, no global ``.read()``.
Every other layer (heap, sequential, B+, hash, catalog) goes through here, which
is what makes :class:`DiskCounter` exact.
"""

import os

from .disk_counter import DiskCounter
from .page import DEFAULT_PAGE_SIZE, VALID_PAGE_SIZES, Page, PageType


class DiskManager:
    """maps page ids to file offsets and is the only place that touches the filesystem."""

    def __init__(self, filepath, page_size=DEFAULT_PAGE_SIZE, counter=None):
        """opens (or creates) the binary file in read/write mode and fixes its block size."""
        if page_size not in VALID_PAGE_SIZES:
            raise ValueError(f"page_size must be one of {VALID_PAGE_SIZES}, got {page_size}")
        self.filepath = filepath
        self.page_size = page_size
        self.counter = counter if counter is not None else DiskCounter()
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if not os.path.exists(filepath):
            open(filepath, "wb").close()
        self._file = open(filepath, "r+b", buffering=0)

    def read_page(self, page_id):
        """seeks to the block offset, reads exactly one block and counts one physical read."""
        self._check_id(page_id)
        self._file.seek(page_id * self.page_size)
        raw = self._file.read(self.page_size)
        if len(raw) != self.page_size:
            raise EOFError(f"page {page_id} is past the end of {self.filepath}")
        self.counter.register_read()
        return raw

    def write_page(self, page_id, data):
        """seeks to the block offset, writes exactly one block and counts one physical write."""
        self._check_id(page_id)
        if len(data) != self.page_size:
            raise ValueError(f"expected {self.page_size} bytes, got {len(data)}")
        self._file.seek(page_id * self.page_size)
        self._file.write(data)
        self.counter.register_write()

    def allocate_page(self, page_type=PageType.HEAP_DATA):
        """appends one zeroed block at the end of the file and returns its new page id."""
        page_id = self.num_pages()
        page = Page(page_id, self.page_size, page_type)
        self.write_page(page_id, page.to_bytes())
        return page_id

    def num_pages(self):
        """derives the page count from the file size, so it never drifts from what is on disk."""
        return os.fstat(self._file.fileno()).st_size // self.page_size

    def truncate(self, num_pages):
        """cuts the file down to the given number of blocks, used to release trailing empty pages."""
        if num_pages < 0:
            raise ValueError("num_pages cannot be negative")
        self._file.truncate(num_pages * self.page_size)

    def _check_id(self, page_id):
        """rejects negative page ids before they turn into a bogus seek offset."""
        if page_id < 0:
            raise ValueError(f"invalid page_id {page_id}")

    def flush(self):
        """forces the operating system to push pending bytes to the physical device."""
        os.fsync(self._file.fileno())

    def close(self):
        """closes the underlying file handle."""
        if not self._file.closed:
            self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"DiskManager({self.filepath!r}, page_size={self.page_size}, pages={self.num_pages()})"
