"""Inspecciona cabeceras, slots y metadatos directamente en un archivo del motor."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.page import Page, PageHeader, HEADER
from backend.core.file_org.heap_file import META as HEAP_META
from backend.core.file_org.sequential_file import META as SEQ_META
from backend.core.indexes.bplus_tree import META as TREE_META
from backend.core.indexes.extendible_hash import META as HASH_META
from backend.core.indexes.bplus_node import NodeSerializer
from backend.core.indexes.hash_bucket import HashBucket
from backend.core.storage.record_serializer import KeyCodec


def inspect(filepath, page_id, page_size):
    if not Path(filepath).is_file():
        raise ValueError("El archivo no existe")
    with DiskManager(filepath, page_size) as dm:
        meta = dm.read_page(0)
        magic = meta[HEADER.size : HEADER.size + 4]
        raw = meta if page_id == 0 else dm.read_page(page_id)
        result = {
            "file": str(Path(filepath).resolve()),
            "page_size": page_size,
            "physical_offset": page_id * page_size,
            "pages_in_file": dm.num_pages(),
            "header": asdict(PageHeader.unpack(raw)),
        }
        if page_id == 0:
            if magic == b"HEP1":
                _, _, rs, free, count = HEAP_META.unpack_from(meta, HEADER.size)
                result["metadata"] = {
                    "kind": "HEAP",
                    "record_size": rs,
                    "free_head": free,
                    "record_count": count,
                }
            elif magic == b"SEQ1":
                _, _, rs, count, fill = SEQ_META.unpack_from(meta, HEADER.size)
                result["metadata"] = {
                    "kind": "SEQUENTIAL",
                    "record_size": rs,
                    "record_count": count,
                    "fill_factor": fill,
                }
            elif magic == b"BPT1":
                _, _, root, maximum, height, dtype = TREE_META.unpack_from(
                    meta, HEADER.size
                )
                result["metadata"] = {
                    "kind": "B+",
                    "root_page_id": root,
                    "max_keys": maximum,
                    "height": height,
                    "key_type": dtype.rstrip(b"\0").decode(),
                }
            elif magic == b"HSH1":
                _, _, depth, capacity, _, dtype = HASH_META.unpack_from(
                    meta, HEADER.size
                )
                result["metadata"] = {
                    "kind": "HASH",
                    "global_depth": depth,
                    "bucket_capacity": capacity,
                    "key_type": dtype.rstrip(b"\0").decode(),
                }
        elif magic in (b"HEP1", b"SEQ1"):
            page = Page.unpack(raw)
            result.update(
                {
                    "record_size": page.record_size,
                    "slot_capacity": page.capacity,
                    "records_offset": page.records_offset,
                    "used_slots": [slot for slot, _ in page.items()],
                    "metadata_hex": page.metadata.hex(),
                }
            )
        elif magic == b"BPT1":
            dtype = TREE_META.unpack_from(meta, HEADER.size)[-1].rstrip(b"\0").decode()
            result["node"] = asdict(
                NodeSerializer(page_size, KeyCodec(dtype)).unpack(raw)
            )
        elif magic == b"HSH1":
            dtype = HASH_META.unpack_from(meta, HEADER.size)[-1].rstrip(b"\0").decode()
            result["bucket"] = asdict(HashBucket.unpack(raw, KeyCodec(dtype)))
        result["inspection_io"] = dm.counter.snapshot()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--page", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=4096)
    args = parser.parse_args()
    print(
        json.dumps(
            inspect(args.file, args.page, args.page_size), indent=2, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
