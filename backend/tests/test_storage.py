"""Unit tests for the physical storage layer: page layout, block I/O and buffer pool."""

import pytest

from backend.storage import (
    HEADER_SIZE,
    SLOT_SIZE,
    VALID_PAGE_SIZES,
    BufferPool,
    DiskCounter,
    DiskManager,
    Page,
    PageFullError,
    PageType,
)


@pytest.fixture
def disk(tmp_path):
    """gives each test a fresh 4 kb file and closes it afterwards."""
    manager = DiskManager(str(tmp_path / "test.dat"), page_size=4096)
    yield manager
    manager.close()


# ---------- page layout ----------

def test_header_roundtrip_preserves_every_field():
    page = Page(7, 4096, PageType.BTREE_LEAF)
    page.next_page_id, page.prev_page_id = 9, 5
    page.insert_record(b"hello")
    restored = Page.from_bytes(page.to_bytes(), 4096)
    assert restored.page_id == 7
    assert restored.page_type is PageType.BTREE_LEAF
    assert restored.next_page_id == 9 and restored.prev_page_id == 5
    assert restored.record_count == 1
    assert restored.get_record(0) == b"hello"


def test_new_page_starts_empty_with_full_free_space():
    page = Page(0, 4096)
    assert page.record_count == 0
    assert page.free_space_offset == HEADER_SIZE
    assert page.free_space == 4096 - HEADER_SIZE


def test_records_are_addressable_by_slot():
    page = Page(0, 4096)
    slots = [page.insert_record(f"row-{i}".encode()) for i in range(5)]
    assert slots == [0, 1, 2, 3, 4]
    for i, slot in enumerate(slots):
        assert page.get_record(slot) == f"row-{i}".encode()


def test_delete_is_logical_and_frees_the_slot_for_reuse():
    page = Page(0, 4096)
    page.insert_record(b"aaa")
    page.insert_record(b"bbb")
    assert page.delete_record(0) is True
    assert page.get_record(0) is None
    assert page.record_count == 1
    reused = page.insert_record(b"ccc")
    assert reused == 0  # tombstone recycled instead of growing the directory
    assert page.slot_count == 2


def test_compact_reclaims_the_bytes_left_by_deletes():
    page = Page(0, 1024)
    for i in range(10):
        page.insert_record(b"x" * 50)
    for slot in range(0, 10, 2):
        page.delete_record(slot)
    before = page.free_space_offset
    page.compact()
    assert page.free_space_offset < before
    assert page.free_space_offset == HEADER_SIZE + 5 * 50
    assert [page.get_record(s) for s in (1, 3, 5, 7, 9)] == [b"x" * 50] * 5


def test_insert_at_index_keeps_slot_order_for_ordered_pages():
    page = Page(0, 4096, PageType.BTREE_LEAF)
    page.insert_record(b"10")
    page.insert_record(b"30")
    page.insert_record(b"20", at=1)
    assert page.records() == [b"10", b"20", b"30"]


def test_remove_slot_shifts_the_directory_up():
    page = Page(0, 4096, PageType.BTREE_INTERNAL)
    for value in (b"a", b"b", b"c"):
        page.insert_record(value)
    page.remove_slot(1)
    assert page.records() == [b"a", b"c"]
    assert page.slot_count == 2


def test_page_full_raises_instead_of_overflowing_the_block():
    page = Page(0, 1024)
    with pytest.raises(PageFullError):
        for _ in range(100):
            page.insert_record(b"y" * 100)


def test_replace_record_handles_both_same_and_different_sizes():
    page = Page(0, 4096)
    page.insert_record(b"short")
    page.replace_record(0, b"tiny!")
    assert page.get_record(0) == b"tiny!"
    page.replace_record(0, b"a much longer value")
    assert page.get_record(0) == b"a much longer value"
    assert page.record_count == 1


@pytest.mark.parametrize("page_size", VALID_PAGE_SIZES)
def test_capacity_scales_with_the_block_size(page_size):
    page = Page(0, page_size)
    count = 0
    while page.can_fit(64):
        page.insert_record(b"z" * 64)
        count += 1
    assert count == (page_size - HEADER_SIZE) // (64 + SLOT_SIZE)


# ---------- disk manager ----------

def test_written_block_reads_back_byte_for_byte(disk):
    page_id = disk.allocate_page()
    page = Page(page_id, disk.page_size)
    page.insert_record(b"persisted")
    disk.write_page(page_id, page.to_bytes())
    assert Page.from_bytes(disk.read_page(page_id), disk.page_size).get_record(0) == b"persisted"


def test_num_pages_comes_from_the_file_size(disk):
    assert disk.num_pages() == 0
    for expected in range(1, 4):
        disk.allocate_page()
        assert disk.num_pages() == expected


def test_counter_increments_once_per_block(disk):
    disk.counter.reset()
    page_id = disk.allocate_page()          # 1 write
    disk.read_page(page_id)                 # 1 read
    disk.write_page(page_id, b"\x00" * disk.page_size)  # 1 write
    assert disk.counter.snapshot() == {"disk_reads": 1, "disk_writes": 2}


def test_reading_past_the_end_of_file_fails_loudly(disk):
    with pytest.raises(EOFError):
        disk.read_page(99)


def test_short_write_is_rejected(disk):
    disk.allocate_page()
    with pytest.raises(ValueError):
        disk.write_page(0, b"too short")


def test_invalid_page_size_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        DiskManager(str(tmp_path / "bad.dat"), page_size=3000)


def test_measure_reports_only_the_io_inside_the_block():
    counter = DiskCounter()
    counter.register_read(5)
    with counter.measure() as io:
        counter.register_read(2)
        counter.register_write(3)
    assert io == {"disk_reads": 2, "disk_writes": 3}
    assert counter.disk_reads == 7


# ---------- buffer pool ----------

def test_second_fetch_is_served_from_cache(disk):
    pool = BufferPool(disk, capacity=8)
    page_id = disk.allocate_page()
    disk.counter.reset()
    pool.fetch(page_id)
    pool.fetch(page_id)
    assert disk.counter.disk_reads == 1
    assert pool.stats()["hits"] == 1


def test_dirty_page_is_written_back_on_eviction(disk):
    pool = BufferPool(disk, capacity=1)
    with pool.allocate() as page:
        page.insert_record(b"survives eviction")
        first = page.page_id
    pool.new_page()  # forces the first frame out of a 1-frame pool
    reloaded = Page.from_bytes(disk.read_page(first), disk.page_size)
    assert reloaded.get_record(0) == b"survives eviction"


def test_pinned_pages_are_never_evicted(disk):
    pool = BufferPool(disk, capacity=1)
    first = disk.allocate_page()
    with pool.get(first):
        pool.fetch(disk.allocate_page())
        assert first in pool._frames  # stays resident even though the pool is over capacity
    assert pool.stats()["frames"] <= 1


def test_capacity_one_defeats_caching_across_operations(disk):
    pool = BufferPool(disk, capacity=1)
    a, b = disk.allocate_page(), disk.allocate_page()
    disk.counter.reset()
    for _ in range(3):
        with pool.get(a):
            pass
        with pool.get(b):
            pass
    assert disk.counter.disk_reads == 6  # every access is a real block read


def test_modify_marks_the_page_dirty_without_an_explicit_call(disk):
    pool = BufferPool(disk, capacity=4)
    page_id = disk.allocate_page()
    with pool.modify(page_id) as page:
        page.insert_record(b"auto dirty")
    pool.flush_all()
    assert Page.from_bytes(disk.read_page(page_id), disk.page_size).get_record(0) == b"auto dirty"
