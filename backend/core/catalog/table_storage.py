"""Abre una tabla y sus índices; mantiene consistentes sus RID en cada operación."""

from collections import OrderedDict
from backend.core.storage.disk_manager import DiskManager
from backend.core.storage.record_serializer import RecordSerializer, KeyCodec
from backend.core.file_org.heap_file import HeapFile
from backend.core.file_org.sequential_file import SequentialFile
from backend.core.file_org.overflow_manager import LINK
from backend.core.indexes.bplus_tree import BPlusTree
from backend.core.indexes.extendible_hash import ExtendibleHash


class TableStorage:
    def __init__(self, catalog, table, counter):
        self.catalog, self.table, self.counter = catalog, table, counter
        self.serializer = RecordSerializer(table.columns)
        self.primary_position = [c.name for c in table.columns].index(table.primary_key)
        self.indexes = {}
        self.files = []
        if table.name in catalog.tables:
            required = [table.filename]
            if table.organization == "SEQUENTIAL":
                required.append(table.filename + ".overflow")
            for definition in table.indexes:
                required.append(definition.filename)
                if definition.kind == "HASH":
                    required.append(definition.filename + ".dir")
            for filename in required:
                path = catalog.directory / filename
                if not path.is_file() or path.stat().st_size == 0:
                    raise ValueError(
                        f"Archivo de tabla o índice ausente/vacío: {filename}"
                    )
        try:
            main = self._disk(table.filename)
            if table.organization == "HEAP":
                self.records = HeapFile(main, self.serializer.record_size)
            else:
                overflow = self._disk(table.filename + ".overflow")
                self.records = SequentialFile(
                    main,
                    overflow,
                    self.serializer.record_size,
                    self.key_of,
                    KeyCodec(table.column(table.primary_key).dtype),
                )
            for definition in table.indexes:
                self.indexes[definition.name] = self.open_index(definition)
        except Exception:
            self.close()
            raise

    def _disk(self, filename):
        dm = DiskManager(
            self.catalog.directory / filename, self.table.page_size, self.counter
        )
        self.files.append(dm)
        return dm

    def key_of(self, record):
        return self.serializer.field_value(record, self.primary_position)

    def open_index(self, definition):
        dm = self._disk(definition.filename)
        cls = BPlusTree if definition.kind == "BTREE" else ExtendibleHash
        return cls(dm, key_type=self.table.column(definition.column).dtype)

    def insert(self, values):
        raw = self.serializer.pack(values)
        row = self.serializer.unpack(raw)
        primary_index = next(i for i in self.table.indexes if i.internal)
        if self.indexes[primary_index.name].search(row[self.table.primary_key]):
            raise ValueError(f"PRIMARY KEY duplicada: {row[self.table.primary_key]}")
        rid = (
            self.records.insert(raw)
            if self.table.organization == "HEAP"
            else self.records.insert(self.key_of(raw), raw)
        )
        for definition in self.table.indexes:
            self.indexes[definition.name].insert(row[definition.column], rid)
        return rid

    def delete(self, rid, raw):
        row = self.serializer.unpack(raw)
        if self.records.delete(rid):
            for definition in self.table.indexes:
                self.indexes[definition.name].delete(row[definition.column], rid)
            return True
        return False

    def fetch_rids(self, rids):
        # Buffer local de 32 páginas, vacío al comenzar cada consulta. Reduce relecturas
        # al recuperar muchos RID de la misma página; solo DiskManager cuenta I/O real.
        pages = OrderedDict()
        for rid in rids:
            page_id = rid[0]
            if page_id not in pages:
                if self.table.organization == "HEAP":
                    page = self.records.read_data_page(page_id)
                elif page_id < 0:
                    page = self.records.overflow.heap.read_data_page(-page_id - 1)
                else:
                    page = self.records._read(page_id)
                pages[page_id] = page
                if len(pages) > 32:
                    pages.popitem(last=False)
            pages.move_to_end(page_id)
            raw = pages[page_id].get_record(rid[1])
            if raw is not None:
                if page_id < 0:
                    raw = raw[LINK.size :]
                yield rid, raw

    def close(self):
        for index in self.indexes.values():
            index.close()
        if hasattr(self, "records"):
            self.records.close()
        for dm in self.files:
            dm.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
