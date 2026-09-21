import struct
from backend.core.storage.disk_manager import DiskManager
from backend.core.file_org.heap_file import HeapFile


def test_heap_freelist_persistence_and_reuse(tmp_path):
    path = tmp_path / "heap"
    heap = HeapFile(DiskManager(path, 1024), 100)
    rids = [heap.insert(struct.pack("<q", i).ljust(100, b"\0")) for i in range(200)]
    pages = heap.disk_manager.num_pages()
    assert len(list(heap.scan())) == 200
    heap.delete(rids[3])
    heap.close()
    heap = HeapFile(DiskManager(path, 1024), 100)
    heap.disk_manager.counter.reset()
    rid = heap.insert(b"X" * 100)
    assert rid == rids[3]
    assert heap.disk_manager.num_pages() == pages
    assert heap.disk_manager.counter.disk_reads <= 1
    assert heap.get(rid) == b"X" * 100
    assert len(list(heap.search(lambda raw: raw == b"X" * 100))) == 1
    heap.close()
