import random
import struct
import pytest
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.record_serializer import KeyCodec
from backend.core.file_org.sequential_file import SequentialFile


def open_seq(tmp_path, size=1024):
    return SequentialFile(
        DiskManager(tmp_path / "main", size),
        DiskManager(tmp_path / "over", size),
        80,
        lambda b: struct.unpack_from("<q", b)[0],
        KeyCodec(),
    )


@pytest.mark.parametrize("size", [1024, 4096])
def test_sequential_overflow_delete_reorganize_reopen(tmp_path, size):
    seq = open_seq(tmp_path, size)
    rids = {}
    for key in range(0, 400, 2):
        rids[key] = seq.insert(key, struct.pack("<q", key).ljust(80, b"\0"))
    keys = list(range(1, 399, 2))
    random.Random(9).shuffle(keys)
    for key in keys:
        rids[key] = seq.insert(key, struct.pack("<q", key).ljust(80, b"\0"))
    assert seq.overflow.heap.count > 0
    for key in [0, 1, 200, 201, 398]:
        assert seq.search(key)[0][0] == rids[key]
        assert seq.delete(rids[key])
    expected = sorted(set(range(399)) - {0, 1, 200, 201, 398})
    assert [seq.key_of(data) for _, data in seq.scan()] == expected
    assert [seq.key_of(data) for _, data in seq.range_search(90, 110)] == list(
        range(90, 111)
    )
    seq.close()
    seq = open_seq(tmp_path, size)
    assert len(seq.search(105)) == 1
    seq.reorganize()
    assert seq.overflow.heap.count == 0
    assert seq.overflow_dm.num_pages() == 1
    for page_id in range(1, seq.main_dm.num_pages()):
        page = seq._read(page_id)
        assert page.header.record_count <= max(1, int(page.capacity * 0.75))
    seq.close()
    seq = open_seq(tmp_path, size)
    assert [seq.key_of(data) for _, data in seq.scan()] == expected
    seq.close()


def test_sequential_empty_pages_keep_fences(tmp_path):
    seq = open_seq(tmp_path)
    rids = [seq.insert(k, struct.pack("<q", k).ljust(80, b"\0")) for k in range(50)]
    for rid in rids:
        if rid.page_id == 2:
            seq.delete(rid)
    assert seq.search(45)
    seq.insert(15, struct.pack("<q", 15).ljust(80, b"\0"))
    assert seq.search(15)
    seq.close()


def test_append_after_overflow_creates_new_main_page(tmp_path):
    seq = open_seq(tmp_path)
    for key in range(0, 48, 2):
        seq.insert(key, struct.pack("<q", key).ljust(80, b"\0"))
    for key in range(25, 48, 2):
        seq.insert(key, struct.pack("<q", key).ljust(80, b"\0"))
    assert seq.overflow.heap.count
    before = seq.main_dm.num_pages()
    for key in range(50, 100):
        seq.insert(key, struct.pack("<q", key).ljust(80, b"\0"))
    assert seq.main_dm.num_pages() > before
    values = [seq.key_of(raw) for _, raw in seq.scan()]
    assert values == sorted(values)
    seq.close()
