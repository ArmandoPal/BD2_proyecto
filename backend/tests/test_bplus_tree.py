import random
import pytest
from backend.core.storage.disk_manager import DiskManager
from backend.core.indexes.bplus_tree import BPlusTree


@pytest.mark.parametrize("size", [1024, 2048, 4096, 8192])
def test_bplus_multilevel_random_duplicates_range_reopen(tmp_path, size):
    path = tmp_path / "tree"
    tree = BPlusTree(DiskManager(path, size), order=5)
    items = [(i // 3, (i + 1, 0)) for i in range(600)]
    random.Random(42).shuffle(items)
    for key, rid in items:
        tree.insert(key, rid)
    assert tree.height >= 4
    assert sorted(tree.search(30)) == [(91, 0), (92, 0), (93, 0)]
    expected = sorted((key, rid) for key, rid in items if 35 <= key <= 45)
    assert list(tree.range_search(35, 45)) == [rid for _, rid in expected]
    assert tree.search(-1) == []
    tree.close()
    tree = BPlusTree(DiskManager(path, size), order=5)
    assert len(tree.search(199)) == 3
    for key, rid in items:
        if key < 150:
            assert tree.delete(key, rid)
    assert tree.search(30) == []
    tree.insert(30, (1000, 0))
    assert tree.search(30) == [(1000, 0)]
    leaf, _ = tree._find_leaf((0, (-(2**31), -(2**31))))
    previous = -1
    while True:
        assert leaf.prev_leaf_id == previous
        if leaf.next_leaf_id == -1:
            break
        previous, leaf = leaf.page_id, tree._read_node(leaf.next_leaf_id)
    tree.close()


def test_bplus_fanout_changes_with_page_size(tmp_path):
    orders = []
    for size in [1024, 2048, 4096, 8192]:
        tree = BPlusTree(DiskManager(tmp_path / str(size), size))
        orders.append(tree.order)
        tree.close()
    assert orders == sorted(set(orders))


def test_bplus_char_keys(tmp_path):
    tree = BPlusTree(DiskManager(tmp_path / "tree"), key_type="CHAR(20)")
    for i, key in enumerate(["Lima", "Cusco", "Piura"]):
        tree.insert(key, (1, i))
    assert list(tree.range_search("C", "M")) == [(1, 1), (1, 0)]
    tree.close()
