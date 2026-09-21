"""Extendible Hashing persistente con directorio paginado y hash estable."""

import hashlib
import struct
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.page import PageHeader, HEADER
from backend.core.storage.record_serializer import KeyCodec
from backend.core.storage.rid import RID
from .hash_bucket import HashBucket
from .hash_directory import HashDirectory

META = struct.Struct("<4sIIII32s")
MAX_DEPTH = 20


class ExtendibleHash:
    def __init__(self, disk_manager, bucket_capacity=None, key_type="INT"):
        self.disk_manager = disk_manager
        self.codec = KeyCodec(key_type)
        maximum = (disk_manager.page_size - HEADER.size - 4) // (self.codec.size + 8)
        self.bucket_capacity = bucket_capacity or maximum
        if not 2 <= self.bucket_capacity <= maximum:
            raise ValueError("Capacidad de bucket inválida")
        self.global_depth = 1
        self.directory = HashDirectory(
            DiskManager(
                str(disk_manager.filepath) + ".dir",
                disk_manager.page_size,
                disk_manager.counter,
            )
        )
        if disk_manager.num_pages():
            magic, size, self.global_depth, capacity, version, dtype = META.unpack_from(
                disk_manager.read_page(0), HEADER.size
            )
            if (magic, size, version, dtype.rstrip(b"\0").decode()) != (
                b"HSH1",
                disk_manager.page_size,
                1,
                key_type,
            ):
                raise ValueError("Índice Hash incompatible")
            if bucket_capacity is not None and capacity != bucket_capacity:
                raise ValueError("Capacidad Hash incompatible")
            self.bucket_capacity = capacity
            if self.directory.dm.num_pages() == 0:
                raise ValueError("Falta el directorio Hash")
        else:
            disk_manager.allocate_page(self._metadata())
            for page_id in (1, 2):
                disk_manager.allocate_page(
                    HashBucket(page_id, 1).pack(self.codec, disk_manager.page_size)
                )
            self.directory.write_block(0, [1, 2])

    def _metadata(self):
        return (
            PageHeader(0).pack()
            + META.pack(
                b"HSH1",
                self.disk_manager.page_size,
                self.global_depth,
                self.bucket_capacity,
                1,
                self.codec.dtype.encode(),
            )
        ).ljust(self.disk_manager.page_size, b"\0")

    def _hash(self, key):
        # Python hash(str) cambia entre procesos. BLAKE2 da los mismos bits al reabrir.
        if self.codec.dtype == "FLOAT" and key == 0:
            key = 0.0
        return int.from_bytes(
            hashlib.blake2b(self.codec.pack(key), digest_size=8).digest(), "little"
        )

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: CALCULO DEL BUCKET
    # ============================================================
    def _bucket_index(self, key):
        return self._hash(key) & ((1 << self.global_depth) - 1)

    def _read_bucket(self, page_id):
        bucket = HashBucket.unpack(self.disk_manager.read_page(page_id), self.codec)
        if bucket.page_id != page_id:
            raise ValueError("Identificador de bucket corrupto")
        return bucket

    def _write_bucket(self, bucket):
        self.disk_manager.write_page(
            bucket.page_id, bucket.pack(self.codec, self.disk_manager.page_size)
        )

    def insert(self, key, rid):
        entry = (key, RID(*rid))
        hashed = self._hash(key)
        while True:
            page_id = self.directory.get(self._bucket_index(key))
            bucket = self._read_bucket(page_id)
            if len(bucket.entries) < self.bucket_capacity:
                bucket.entries.append(entry)
                self._write_bucket(bucket)
                return
            same_hash = all(self._hash(k) == hashed for k, _ in bucket.entries)
            if bucket.local_depth >= MAX_DEPTH or same_hash:
                self._append_collision(bucket, entry)
                return
            self._split_bucket(bucket)

    def _append_collision(self, bucket, entry):
        while len(bucket.entries) >= self.bucket_capacity:
            if bucket.next_page_id == -1:
                following = HashBucket(
                    self.disk_manager.num_pages(), bucket.local_depth, [entry]
                )
                self.disk_manager.allocate_page(
                    following.pack(self.codec, self.disk_manager.page_size)
                )
                bucket.next_page_id = following.page_id
                self._write_bucket(bucket)
                return
            bucket = self._read_bucket(bucket.next_page_id)
        bucket.entries.append(entry)
        self._write_bucket(bucket)

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: DUPLICACION DEL DIRECTORIO
    # ============================================================
    def _double_directory(self):
        self.directory.double(1 << self.global_depth)
        self.global_depth += 1
        self.disk_manager.write_page(0, self._metadata())

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: SPLIT Y REDISTRIBUCION DE BUCKET
    # ============================================================
    def _split_bucket(self, bucket):
        if bucket.local_depth == self.global_depth:
            self._double_directory()
        old_entries, old_next = bucket.entries, bucket.next_page_id
        bucket.local_depth += 1
        bucket.entries, bucket.next_page_id = [], -1
        right = HashBucket(self.disk_manager.num_pages(), bucket.local_depth)
        self.disk_manager.allocate_page(
            right.pack(self.codec, self.disk_manager.page_size)
        )
        self._write_bucket(bucket)
        self.directory.redirect(
            bucket.page_id, right.page_id, bucket.local_depth, 1 << self.global_depth
        )
        while True:
            for entry in old_entries:
                target = (
                    right
                    if self._hash(entry[0]) & (1 << (bucket.local_depth - 1))
                    else bucket
                )
                # Releer la cabecera evita reutilizar un enlace anterior tras añadir colisiones.
                self._append_collision(self._read_bucket(target.page_id), entry)
            if old_next == -1:
                break
            old = self._read_bucket(old_next)
            old_entries, old_next = old.entries, old.next_page_id
            old.entries, old.next_page_id = [], -1
            self._write_bucket(old)

    def search(self, key):
        return list(self.iter_search(key))

    def iter_search(self, key):
        page_id = self.directory.get(self._bucket_index(key))
        while page_id != -1:
            bucket = self._read_bucket(page_id)
            for stored, rid in bucket.entries:
                if stored == key:
                    yield rid
            page_id = bucket.next_page_id

    def delete(self, key, rid):
        page_id = self.directory.get(self._bucket_index(key))
        while page_id != -1:
            bucket = self._read_bucket(page_id)
            entry = (key, RID(*rid))
            if entry in bucket.entries:
                bucket.entries.remove(entry)
                self._write_bucket(bucket)
                return True
            page_id = bucket.next_page_id
        return False

    def close(self):
        self.disk_manager.close()
        self.directory.dm.close()
