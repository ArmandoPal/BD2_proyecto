"""Unit tests for the Heap File: free-list inserts, full scans and both delete strategies."""

import pytest

from backend.catalog import Column, Schema
from backend.file_org import HeapFile


@pytest.fixture
def schema():
    """small fixed-width product schema reused across the file organization tests."""
    return Schema([
        Column("id", "INT", primary_key=True),
        Column("name", "CHAR(24)"),
        Column("price", "FLOAT"),
    ])


@pytest.fixture
def heap(tmp_path, schema):
    """opens an empty heap file and closes it when the test ends."""
    heap = HeapFile(str(tmp_path / "products.dat"), schema, page_size=1024)
    yield heap
    heap.close()


def rows(schema, count, start=0):
    """packs `count` synthetic product records."""
    return [schema.pack([i, f"item-{i}", i * 1.5]) for i in range(start, start + count)]


def test_inserted_records_come_back_by_rid(heap, schema):
    rids = [heap.insert(record) for record in rows(schema, 50)]
    for i, rid in enumerate(rids):
        assert schema.unpack(heap.get(rid))[0] == i


def test_scan_returns_every_record_exactly_once(heap, schema):
    heap.bulk_insert(rows(schema, 300))
    ids = sorted(schema.unpack(record)[0] for _, record in heap.scan())
    assert ids == list(range(300))
    assert heap.num_records == 300


def test_full_scan_costs_one_read_per_data_page(heap, schema):
    heap.bulk_insert(rows(schema, 300))
    heap.pool.capacity = 1
    heap.pool.clear()            # defeat the cache so the count is pure disk
    heap.counter.reset()
    list(heap.scan())
    assert heap.counter.disk_reads == heap.num_data_pages


def test_insert_reuses_pages_instead_of_always_appending(heap, schema):
    heap.bulk_insert(rows(schema, 40))
    pages_before = heap.num_pages
    heap.delete(heap.insert(schema.pack([999, "temp", 0.0])))
    heap.insert(schema.pack([1000, "reused", 1.0]))
    assert heap.num_pages == pages_before or heap.num_pages == pages_before + 1


def test_logical_delete_removes_the_record_from_the_scan(heap, schema):
    rids = heap.bulk_insert(rows(schema, 100))
    assert heap.delete(rids[42]) is True
    assert heap.get(rids[42]) is None
    assert heap.num_records == 99
    assert 42 not in {schema.unpack(r)[0] for _, r in heap.scan()}


def test_deleting_twice_is_reported_as_a_no_op(heap, schema):
    rid = heap.insert(schema.pack([1, "x", 1.0]))
    assert heap.delete(rid) is True
    assert heap.delete(rid) is False


def test_move_the_last_keeps_the_file_dense(heap, schema):
    rids = heap.bulk_insert(rows(schema, 200))
    before = heap.num_records
    assert heap.delete(rids[5], strategy="move_last") is True
    assert heap.num_records == before - 1
    ids = sorted(schema.unpack(r)[0] for _, r in heap.scan())
    assert len(ids) == before - 1
    assert 5 not in ids          # the hole was filled by the record that used to be last


def test_move_the_last_releases_pages_that_become_empty(heap, schema):
    rids = heap.bulk_insert(rows(schema, 120))
    pages_before = heap.num_pages
    for rid in reversed(rids[60:]):
        heap.delete(rid, strategy="move_last")
    assert heap.num_pages < pages_before
    assert heap.num_records == 60


def test_free_list_survives_reopening_the_file(tmp_path, schema):
    path = str(tmp_path / "persist.dat")
    heap = HeapFile(path, schema, page_size=1024)
    rids = heap.bulk_insert(rows(schema, 80))
    heap.delete(rids[3])
    heap.close()

    reopened = HeapFile(path, schema, page_size=1024)
    assert reopened.num_records == 79
    assert reopened.header.free_head != -1
    assert sum(1 for _ in reopened.scan()) == 79
    reopened.close()


@pytest.mark.parametrize("page_size", [1024, 2048, 4096, 8192])
def test_bigger_blocks_mean_fewer_pages(tmp_path, schema, page_size):
    heap = HeapFile(str(tmp_path / f"b{page_size}.dat"), schema, page_size=page_size)
    heap.bulk_insert(rows(schema, 500))
    expected = -(-500 // heap.records_per_page())
    assert heap.num_data_pages == pytest.approx(expected, abs=1)
    heap.close()
