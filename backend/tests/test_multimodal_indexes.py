import math
import random
from collections import Counter
import numpy as np
import pytest
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.rid import RID
from backend.core.multimodal.paged import BlobStore, FixedArray, pack_rid, unpack_rid
from backend.core.multimodal.rtree import RTree, mindist


def test_fixed_array_crosses_pages_and_reopens(tmp_path):
    counter = DiskCounter()
    array = FixedArray(tmp_path / "array.idx", "<Qd", counter)
    array.write_all((i, i/3) for i in range(2000))
    array.close()
    array = FixedArray(tmp_path / "array.idx", "<Qd", counter)
    counter.reset()
    assert array.find(1999) == (1999, 1999/3)
    assert 0 < counter.disk_reads < 9
    assert len(list(array.rows())) == 2000
    assert array.find(3000) is None
    array.close()


def test_blob_round_trip(tmp_path):
    blobs = BlobStore(tmp_path / "images.blobs")
    content = bytes(range(256))*100
    first = blobs.append(content)
    second = blobs.append(b"other")
    blobs.close()
    blobs = BlobStore(tmp_path / "images.blobs")
    assert blobs.get(first) == content
    assert blobs.get(second) == b"other"
    assert blobs.disk.filepath.stat().st_size % 4096 == 0
    blobs.close()


@pytest.mark.parametrize("dimensions", [2, 4, 16, 128])
def test_rtree_recursive_splits_reopen_knn_and_window(tmp_path, dimensions):
    rng = random.Random(42)
    points = [tuple(rng.random() for _ in range(dimensions)) for _ in range(180)]
    path = tmp_path / "spatial.idx"
    tree = RTree(path, dimensions=dimensions, max_entries=5)
    for i, point in enumerate(points):
        tree.insert(point+point, RID(i+1, 0))
    assert tree.root != 1
    tree.close()
    tree = RTree(path)
    q = (.47,)*dimensions
    expected = sorted(range(len(points)), key=lambda i: (math.dist(points[i], q), i))[:20]
    result = tree.knn(q, 20)
    assert [rid.page_id-1 for rid, _ in result] == expected
    box = (.2,)*dimensions + (.8,)*dimensions
    assert {rid.page_id-1 for rid in tree.window(box)} == {i for i, p in enumerate(points) if all(.2 <= v <= .8 for v in p)}
    tree.close()


def test_rtree_duplicate_points_and_rectangles(tmp_path):
    tree = RTree(tmp_path / "geo.idx", max_entries=4)
    for i in range(50):
        tree.insert((1, 1, 2, 3), RID(i+1, 0))
    assert len(tree.window((1.5, 1.5, 1.6, 1.6))) == 50
    assert [rid.page_id for rid, _ in tree.knn((1.5, 2), 3)] == [1, 2, 3]
    with pytest.raises(ValueError):
        tree.insert((2, 2, 1, 1), RID(51, 0))
    tree.close()

