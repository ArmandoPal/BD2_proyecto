"""Mandatory physical I/O monitor (enunciado 3.1).

Counts exactly two variables: ``disk_reads`` and ``disk_writes``, in whole
blocks. Only :class:`~backend.storage.disk_manager.DiskManager` may increment
them, so the totals are exact by construction rather than by audit.
"""

from contextlib import contextmanager


class DiskCounter:
    """counts block reads and writes; one instance is shared by every file of an engine."""

    __slots__ = ("disk_reads", "disk_writes")

    def __init__(self):
        """starts both counters at zero."""
        self.disk_reads = 0
        self.disk_writes = 0

    def register_read(self, blocks=1):
        """adds the given number of physical block reads."""
        self.disk_reads += blocks

    def register_write(self, blocks=1):
        """adds the given number of physical block writes."""
        self.disk_writes += blocks

    def reset(self):
        """zeroes both counters, typically before timing a single query."""
        self.disk_reads = 0
        self.disk_writes = 0

    def snapshot(self):
        """returns the current totals as a plain dict."""
        return {"disk_reads": self.disk_reads, "disk_writes": self.disk_writes}

    def since(self, snapshot):
        """returns how much I/O happened after a previous snapshot, without resetting."""
        return {
            "disk_reads": self.disk_reads - snapshot["disk_reads"],
            "disk_writes": self.disk_writes - snapshot["disk_writes"],
        }

    @contextmanager
    def measure(self):
        """context manager that yields a dict filled with the I/O performed inside the block."""
        start = self.snapshot()
        result = {"disk_reads": 0, "disk_writes": 0}
        try:
            yield result
        finally:
            result.update(self.since(start))

    def __repr__(self):
        return f"DiskCounter(reads={self.disk_reads}, writes={self.disk_writes})"
