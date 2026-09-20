"""Buffer manager: the RAM cache that sits between the access methods and the disk.

Holds a bounded set of frames with an LRU victim policy and write-back on
eviction. Frames in use are pinned so they are never stolen mid-operation.

Capacity is a constructor argument on purpose: ``capacity=1`` makes every
unpinned page go straight back to disk, which is the configuration the
benchmarks need so that the measured I/O reflects the access method and not a
warm cache.
"""

from collections import OrderedDict
from contextlib import contextmanager

from .page import Page, PageType


class _Frame:
    """one cached page plus its dirty flag and pin count."""

    __slots__ = ("page", "dirty", "pins")

    def __init__(self, page):
        self.page = page
        self.dirty = False
        self.pins = 0


class BufferPool:
    """caches pages in memory, evicting the least recently used unpinned frame when full."""

    def __init__(self, disk_manager, capacity=64):
        """binds the pool to one file and fixes how many frames it may hold."""
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self.disk = disk_manager
        self.capacity = capacity
        self._frames = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def page_size(self):
        """block size of the underlying file, exposed so callers need not reach into the disk manager."""
        return self.disk.page_size

    def fetch(self, page_id):
        """returns a page from cache on a hit, otherwise reads it from disk and caches it."""
        frame = self._frames.get(page_id)
        if frame is not None:
            self._frames.move_to_end(page_id)
            self.hits += 1
            return frame.page
        self.misses += 1
        page = Page.from_bytes(self.disk.read_page(page_id), self.disk.page_size)
        self._frames[page_id] = _Frame(page)
        self._trim()
        return page

    def new_page(self, page_type=PageType.HEAP_DATA):
        """allocates a fresh block on disk and returns it already cached and marked dirty."""
        page_id = self.disk.allocate_page(page_type)
        page = Page(page_id, self.disk.page_size, page_type)
        frame = _Frame(page)
        frame.dirty = True
        self._frames[page_id] = frame
        self._trim()
        return page

    def mark_dirty(self, page_id):
        """flags a cached page so it is written back before it is evicted or flushed."""
        frame = self._frames.get(page_id)
        if frame is None:
            raise KeyError(f"page {page_id} is not in the buffer pool")
        frame.dirty = True

    def pin(self, page_id):
        """protects a frame from eviction while an operation is still using it."""
        self._frames[page_id].pins += 1

    def unpin(self, page_id):
        """releases one pin and lets the pool shrink back to its capacity."""
        frame = self._frames.get(page_id)
        if frame is None:
            return
        frame.pins = max(0, frame.pins - 1)
        self._trim()

    @contextmanager
    def get(self, page_id):
        """pins a page for read-only use and unpins it when the block exits."""
        page = self.fetch(page_id)
        self.pin(page_id)
        try:
            yield page
        finally:
            self.unpin(page_id)

    @contextmanager
    def modify(self, page_id):
        """same as get() but marks the page dirty, so the caller cannot forget to."""
        page = self.fetch(page_id)
        self.pin(page_id)
        self.mark_dirty(page_id)
        try:
            yield page
        finally:
            self.unpin(page_id)

    @contextmanager
    def allocate(self, page_type=PageType.HEAP_DATA):
        """creates a new page, keeps it pinned while it is being filled, then releases it."""
        page = self.new_page(page_type)
        self.pin(page.page_id)
        try:
            yield page
        finally:
            self.unpin(page.page_id)

    def _trim(self):
        """evicts least recently used unpinned frames until the pool fits its capacity."""
        while len(self._frames) > self.capacity:
            victim = self._pick_victim()
            if victim is None:
                return  # everything is pinned: stay over capacity rather than corrupt state
            self._evict(victim)

    def _pick_victim(self):
        """returns the oldest unpinned page id, or None when every frame is in use."""
        for page_id, frame in self._frames.items():
            if frame.pins == 0:
                return page_id
        return None

    def _evict(self, page_id):
        """writes the frame back if dirty and drops it from the cache."""
        frame = self._frames.pop(page_id)
        if frame.dirty:
            self.disk.write_page(page_id, frame.page.to_bytes())

    def flush(self, page_id):
        """writes one dirty page back to disk while keeping it cached."""
        frame = self._frames.get(page_id)
        if frame is not None and frame.dirty:
            self.disk.write_page(page_id, frame.page.to_bytes())
            frame.dirty = False

    def flush_all(self):
        """writes every dirty page back to disk, leaving the cache populated but clean."""
        for page_id in list(self._frames):
            self.flush(page_id)

    def close(self):
        """flushes everything and closes the file; the pool is unusable afterwards."""
        self.flush_all()
        self.disk.close()

    def stats(self):
        """returns cache hit/miss counters, useful to explain benchmark numbers."""
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_ratio": (self.hits / total) if total else 0.0,
            "frames": len(self._frames),
            "capacity": self.capacity,
        }

    def __repr__(self):
        return f"BufferPool(capacity={self.capacity}, frames={len(self._frames)})"
