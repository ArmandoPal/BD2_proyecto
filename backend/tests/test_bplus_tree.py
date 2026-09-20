"""Unit tests for the on-disk B+ tree: splits, point and range search, fan-out vs block size."""

import math
import random

import pytest

from backend.indexes import BPlusTree


@pytest.fixture
def tree(tmp_path):
    """small-page tree so splits happen after a handful of inserts."""
    tree = BPlusTree(str(tmp_path / "idx.idx"), "INT", page_size=1024)
    yield tree
    tree.close()


def load(tree, keys):
    """inserts one entry per key, deriving a deterministic RID from the key."""
    for key in keys:
        tree.insert(key, (key // 10, key % 10))


def test_single_entry_tree_is_one_leaf(tree):
    tree.insert(5, (0, 5))
    assert tree.depth == 1
    assert tree.search(5) == [(0, 5)]


def test_point_search_finds_every_key_after_random_inserts(tree):
    keys = list(range(5000))
    random.Random(1).shuffle(keys)
    load(tree, keys)
    assert all(tree.search(k) == [(k // 10, k % 10)] for k in range(0, 5000, 61))


def test_missing_key_returns_nothing(tree):
    load(tree, range(500))
    assert tree.search(99999) == []


def test_tree_grows_in_height_not_in_leaf_size(tree):
    load(tree, range(5000))
    assert tree.depth >= 3
    assert tree.num_entries == 5000


def test_leaf_chain_yields_every_key_in_order(tree):
    keys = list(range(3000))
    random.Random(2).shuffle(keys)
    load(tree, keys)
    assert [key for key, _ in tree.scan()] == list(range(3000))


def test_range_search_is_a_closed_interval(tree):
    load(tree, range(2000))
    assert [k for k, _ in tree.range_search(500, 520)] == list(range(500, 521))


def test_inverted_range_returns_nothing(tree):
    load(tree, range(100))
    assert tree.range_search(80, 20) == []


def test_point_lookup_costs_at_most_the_height(tmp_path):
    tree = BPlusTree(str(tmp_path / "cost.idx"), "INT", page_size=1024)
    load(tree, range(20000))
    tree.pool.capacity = 1
    tree.pool.clear()
    tree.counter.reset()
    tree.search(12345)
    assert tree.counter.disk_reads <= tree.depth + 1
    tree.close()


def test_duplicate_keys_are_all_returned(tree):
    for slot in range(40):
        tree.insert(7, (1, slot))
    assert len(tree.search(7)) == 40


def test_delete_removes_one_rid_or_all_of_them(tree):
    for slot in range(5):
        tree.insert(9, (2, slot))
    assert tree.delete(9, (2, 3)) == 1
    assert len(tree.search(9)) == 4
    assert tree.delete(9) == 4
    assert tree.search(9) == []


def test_state_survives_reopening(tmp_path):
    path = str(tmp_path / "persist.idx")
    tree = BPlusTree(path, "INT", page_size=1024)
    load(tree, range(4000))
    height, entries = tree.depth, tree.num_entries
    tree.close()

    reopened = BPlusTree(path, "INT", page_size=1024)
    assert (reopened.depth, reopened.num_entries) == (height, entries)
    assert reopened.search(3999) == [(399, 9)]
    reopened.close()


def test_char_keys_are_supported(tmp_path):
    tree = BPlusTree(str(tmp_path / "s.idx"), "CHAR(8)", page_size=1024)
    for position, name in enumerate(["ada", "grace", "alan", "edsger", "barbara"]):
        tree.insert(name, (0, position))
    assert [k for k, _ in tree.scan()] == ["ada", "alan", "barbara", "edsger", "grace"]
    assert tree.search("alan") == [(0, 2)]
    tree.close()


@pytest.mark.parametrize("page_size", [1024, 2048, 4096, 8192])
def test_bigger_blocks_give_more_fan_out_and_less_height(tmp_path, page_size):
    tree = BPlusTree(str(tmp_path / f"f{page_size}.idx"), "INT", page_size=page_size)
    load(tree, range(20000))
    assert tree.fan_out() >= page_size // 128
    assert tree.depth <= math.ceil(math.log(20000, tree.fan_out())) + 1
    tree.close()
