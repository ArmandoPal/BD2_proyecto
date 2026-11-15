import math
import random
from collections import Counter
import numpy as np
import pytest
from backend.core.storage.disk_counter import DiskCounter
from backend.core.storage.rid import RID
from backend.core.multimodal.paged import BlobStore, FixedArray, pack_rid, unpack_rid


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

