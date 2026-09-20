"""Unit tests for the Sequential File: binary search, overflow chains and reorganization."""

import random

import pytest

from backend.catalog import Column, Schema
from backend.file_org import MAIN, OVERFLOW, SequentialFile


@pytest.fixture
def schema():
    """same product schema as the heap tests, keyed by id."""
    return Schema([
        Column("id", "INT", primary_key=True),
        Column("name", "CHAR(24)"),
        Column("price", "FLOAT"),
    ])


@pytest.fixture
def seq(tmp_path, schema):
    """opens an empty sequential file keyed by id and closes it afterwards."""
    seq = SequentialFile(str(tmp_path / "products.dat"), schema, "id", page_size=1024)
    yield seq
    seq.close()


def packed(schema, ids):
    """packs one record per id."""
    return [schema.pack([i, f"item-{i}", i * 1.5]) for i in ids]


def test_sorted_load_fills_the_main_area_without_overflow(seq, schema):
    seq.bulk_insert(packed(schema, range(1000)))
    assert seq.overflow_pages() == 0
    assert seq.num_main_pages > 1


def test_random_load_pushes_records_into_the_overflow_area(seq, schema):
    ids = list(range(1000))
    random.Random(7).shuffle(ids)
    seq.bulk_insert(packed(schema, ids))
    assert seq.overflow_pages() > 0


def test_scan_is_always_in_key_order_even_with_overflow(seq, schema):
    ids = list(range(800))
    random.Random(11).shuffle(ids)
    seq.bulk_insert(packed(schema, ids))
    assert [schema.unpack(r)[0] for _, r in seq.scan()] == list(range(800))


def test_point_search_finds_records_in_both_areas(seq, schema):
    ids = list(range(500))
    random.Random(3).shuffle(ids)
    seq.bulk_insert(packed(schema, ids))
    areas = set()
    for key in (0, 123, 499):
        found = seq.search(key)
        assert [schema.unpack(r)[0] for _, r in found] == [key]
        areas.add(found[0][0][0])
    assert areas <= {MAIN, OVERFLOW}


def test_search_for_a_missing_key_returns_nothing(seq, schema):
    seq.bulk_insert(packed(schema, range(100)))
    assert seq.search(9999) == []


def test_range_search_returns_a_closed_interval_in_order(seq, schema):
    seq.bulk_insert(packed(schema, range(600)))
    found = [schema.unpack(r)[0] for _, r in seq.range_search(100, 150)]
    assert found == list(range(100, 151))


def test_binary_search_is_logarithmic_in_the_number_of_pages(seq, schema):
    seq.bulk_insert(packed(schema, range(4000)))
    seq.pool.capacity = 1
    seq.pool.clear()                      # no cache: count real block reads
    seq.counter.reset()
    seq.search(2500)
    import math
    assert seq.counter.disk_reads <= 2 * math.ceil(math.log2(seq.num_main_pages)) + 4


def test_reorganize_empties_overflow_and_rebuilds_the_main_area(seq, schema):
    ids = list(range(1500))
    random.Random(5).shuffle(ids)
    seq.bulk_insert(packed(schema, ids))
    assert seq.overflow_pages() > 0

    stats = seq.reorganize()
    assert stats["records"] == 1500
    assert seq.overflow_pages() == 0
    assert [schema.unpack(r)[0] for _, r in seq.scan()] == list(range(1500))


def test_reorganize_respects_the_fill_factor(tmp_path, schema):
    seq = SequentialFile(str(tmp_path / "ff.dat"), schema, "id", page_size=1024, fill_factor=0.75)
    seq.bulk_insert(packed(schema, range(2000)))
    seq.reorganize()
    target = max(1, int(seq.records_per_page() * 0.75))
    assert seq.num_main_pages == -(-2000 // target)
    seq.close()


def test_fill_factor_is_clamped_to_the_allowed_band(tmp_path, schema):
    tight = SequentialFile(str(tmp_path / "a.dat"), schema, "id", fill_factor=0.2)
    loose = SequentialFile(str(tmp_path / "b.dat"), schema, "id", fill_factor=0.99)
    assert tight.fill_factor == 0.70 and loose.fill_factor == 0.80
    tight.close()
    loose.close()


def test_delete_removes_the_key_from_later_searches(seq, schema):
    seq.bulk_insert(packed(schema, range(400)))
    assert seq.delete(200) == 1
    assert seq.search(200) == []
    assert seq.num_records == 399


def test_state_survives_reopening_the_file(tmp_path, schema):
    path = str(tmp_path / "persist.dat")
    seq = SequentialFile(path, schema, "id", page_size=1024)
    ids = list(range(700))
    random.Random(13).shuffle(ids)
    seq.bulk_insert(packed(schema, ids))
    seq.close()

    reopened = SequentialFile(path, schema, "id", page_size=1024)
    assert reopened.num_records == 700
    assert [schema.unpack(r)[0] for _, r in reopened.scan()] == list(range(700))
    reopened.close()
