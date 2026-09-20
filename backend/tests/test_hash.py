"""Unit tests for extendible hashing: bucket splits, directory doubling and O(1) lookups."""

import random

import pytest

from backend.indexes import ExtendibleHash


@pytest.fixture
def index(tmp_path):
    """small-page hash index so buckets fill quickly and the directory has to double."""
    index = ExtendibleHash(str(tmp_path / "h.idx"), "INT", page_size=1024)
    yield index
    index.close()


def load(index, keys):
    """inserts one entry per key, deriving a deterministic RID from the key."""
    for key in keys:
        index.insert(key, (key // 10, key % 10))


def test_empty_index_starts_with_one_bucket(index):
    stats = index.stats()
    assert stats["global_depth"] == 0
    assert stats["directory_slots"] == 1


def test_every_inserted_key_is_found(index):
    keys = list(range(5000))
    random.Random(3).shuffle(keys)
    load(index, keys)
    assert all(index.search(k) == [(k // 10, k % 10)] for k in range(0, 5000, 37))


def test_missing_key_returns_nothing(index):
    load(index, range(300))
    assert index.search(123456) == []


def test_directory_doubles_as_buckets_overflow(index):
    load(index, range(5000))
    stats = index.stats()
    assert stats["global_depth"] > 0
    assert stats["directory_slots"] == 2 ** stats["global_depth"]
    assert stats["entries"] == 5000


def test_lookup_cost_does_not_grow_with_the_table(tmp_path):
    costs = []
    for size in (2000, 20000):
        index = ExtendibleHash(str(tmp_path / f"n{size}.idx"), "INT", page_size=1024)
        load(index, range(size))
        index.pool.capacity = 2
        index.pool.clear()
        index.counter.reset()
        index.search(size // 2)
        costs.append(index.counter.disk_reads)
        index.close()
    assert costs[0] == costs[1] <= 2     # O(1) block transfers regardless of N


def test_duplicate_keys_are_all_returned(index):
    for slot in range(30):
        index.insert(11, (1, slot))
    assert len(index.search(11)) == 30


def test_identical_keys_beyond_a_bucket_chain_instead_of_looping(index):
    for slot in range(500):
        index.insert(42, (2, slot % 60))
    assert len(index.search(42)) == 500


def test_delete_removes_one_rid_or_all_of_them(index):
    for slot in range(4):
        index.insert(8, (3, slot))
    assert index.delete(8, (3, 2)) == 1
    assert len(index.search(8)) == 3
    assert index.delete(8) == 3
    assert index.search(8) == []


def test_scan_returns_every_entry(index):
    load(index, range(1500))
    assert sorted(key for key, _ in index.scan()) == list(range(1500))


def test_directory_survives_reopening(tmp_path):
    path = str(tmp_path / "persist.idx")
    index = ExtendibleHash(path, "INT", page_size=1024)
    load(index, range(6000))
    depth, entries = index.depth, index.num_entries
    index.close()

    reopened = ExtendibleHash(path, "INT", page_size=1024)
    assert (reopened.depth, reopened.num_entries) == (depth, entries)
    assert reopened.search(5999) == [(599, 9)]
    reopened.close()


def test_char_keys_are_supported(tmp_path):
    index = ExtendibleHash(str(tmp_path / "s.idx"), "CHAR(12)", page_size=1024)
    for position, name in enumerate(["laptop", "mouse", "teclado", "monitor"]):
        index.insert(name, (0, position))
    assert index.search("teclado") == [(0, 2)]
    assert index.search("tablet") == []
    index.close()
