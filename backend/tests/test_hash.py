import random
from backend.core.storage.disk_manager import DiskManager
from backend.core.indexes.extendible_hash import ExtendibleHash


def test_hash_splits_directory_reopen_and_delete(tmp_path):
    path = tmp_path / "hash"
    index = ExtendibleHash(DiskManager(path, 1024), bucket_capacity=3)
    keys = list(range(600))
    random.Random(5).shuffle(keys)
    for key in keys:
        index.insert(key, (key + 1, 0))
    assert index.global_depth > 1
    assert index.directory.dm.num_pages() > 1
    for key in keys:
        assert index.search(key) == [(key + 1, 0)]
    depth = index.global_depth
    index.close()
    index = ExtendibleHash(DiskManager(path, 1024), bucket_capacity=3)
    assert index.global_depth == depth
    for key in keys[:100]:
        assert index.delete(key, (key + 1, 0))
    for key in keys[:100]:
        assert index.search(key) == []
    for key in keys[100:]:
        assert index.search(key) == [(key + 1, 0)]
    index.close()


def test_hash_duplicate_collision_chain_and_later_splits(tmp_path):
    index = ExtendibleHash(DiskManager(tmp_path / "hash", 1024), bucket_capacity=3)
    for i in range(40):
        index.insert(7, (1, i))
    for i in range(200):
        if i != 7:
            index.insert(i, (i + 2, 0))
    assert sorted(index.search(7)) == [(1, i) for i in range(40)]
    assert index.delete(7, (1, 3))
    assert len(index.search(7)) == 39
    index.close()


def test_hash_strings_persist_and_signed_float_zero(tmp_path):
    for dtype, key, equivalent in [("CHAR(10)", "Perú", "Perú"), ("FLOAT", -0.0, 0.0)]:
        path = tmp_path / dtype.replace("(", "").replace(")", "")
        index = ExtendibleHash(DiskManager(path), key_type=dtype)
        index.insert(key, (1, 1))
        index.close()
        index = ExtendibleHash(DiskManager(path), key_type=dtype)
        assert index.search(equivalent) == [(1, 1)]
        index.close()
