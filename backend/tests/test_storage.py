import pytest
from backend.core.storage.page import Page, PageHeader
from backend.core.storage.rid import RID
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.record_serializer import RecordSerializer


@pytest.mark.parametrize("size", [1024, 2048, 4096, 8192])
def test_page_layout_roundtrip(size):
    page = Page(7, 100, size)
    slot = page.insert_record(b"A" * 100)
    packed = page.pack()
    assert len(packed) == size
    assert PageHeader.unpack(packed).page_id == 7
    assert packed[page.records_offset : page.records_offset + 100] == b"A" * 100
    restored = Page.unpack(packed)
    assert restored.get_record(slot) == b"A" * 100
    restored.delete_record(slot)
    assert restored.insert_record(b"B" * 100) == slot
    assert RID(7, slot) == (7, slot)


def test_disk_offset_counter_and_reopen(tmp_path):
    counter = DiskCounter()
    path = tmp_path / "pages.bin"
    with DiskManager(path, 1024, counter) as dm:
        dm.allocate_page(b"A" * 1024)
        dm.allocate_page(b"B" * 1024)
        dm.write_page(0, b"C" * 1024)
        assert dm.read_page(1) == b"B" * 1024
        assert counter.snapshot() == {"disk_reads": 1, "disk_writes": 3}
        with pytest.raises(ValueError):
            dm.read_page(2)
        with pytest.raises(ValueError):
            dm.write_page(0, b"bad")
    with path.open("rb") as raw:
        raw.seek(1024)
        assert raw.read(1024) == b"B" * 1024
    with DiskManager(path, 1024, counter) as dm:
        assert dm.read_page(0) == b"C" * 1024
    counter.reset()
    assert counter.disk_reads == counter.disk_writes == 0


def test_corrupt_page_and_file_rejected(tmp_path):
    page = Page(1, 32, 1024)
    raw = bytearray(page.pack())
    raw[4] = 1
    with pytest.raises(ValueError):
        Page.unpack(raw)
    path = tmp_path / "bad"
    path.write_bytes(b"broken")
    with pytest.raises(ValueError):
        DiskManager(path)


def test_serializer_types_and_limits():
    codec = RecordSerializer([("id", "INT"), ("price", "FLOAT"), ("name", "CHAR(5)")])
    raw = codec.pack([2**40, 1.25, "Perú"])
    assert codec.unpack(raw) == {"id": 2**40, "price": 1.25, "name": "Perú"}
    for values in [
        [1.2, 1.0, "ok"],
        [1, float("nan"), "ok"],
        [1, 2, "abcdef"],
        [1, 2, "a\0"],
    ]:
        with pytest.raises(ValueError):
            codec.pack(values)
