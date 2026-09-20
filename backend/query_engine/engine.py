"""Database facade: owns the catalog, the open table files and the open indexes.

This is the object the REST layer talks to. It lazily opens the binary file
behind each table and each index, keeps one :class:`DiskCounter` shared by all
of them so a query's I/O is measured end to end, and closes everything on
shutdown.

Two deliberate design rules:

* Indexes are only allowed on ``HEAP`` tables. A sequential file shifts slots
  when it inserts in sorted position, so a stored RID would not stay valid; a
  sequential table is searched with binary search instead, which is exactly the
  comparison the experiments in the enunciado ask for.
* A table that carries indexes always deletes logically (free-list), never with
  move-the-last, because moving a record would invalidate the RIDs the index
  points at.
"""

import os

from backend.catalog import Column, IndexDef, SchemaManager, TableDef
from backend.catalog.schema_manager import CatalogError
from backend.file_org import HeapFile, SequentialFile
from backend.indexes import BPlusTree, ExtendibleHash
from backend.storage import DiskCounter

INDEX_CLASSES = {"BTREE": BPlusTree, "HASH": ExtendibleHash}


class Database:
    """one database directory: catalog, table files and index files, all sharing an I/O counter."""

    def __init__(self, base_dir="data/processed", page_size=4096, buffer_capacity=64, counter=None):
        """opens (or creates) the database directory and loads the catalog."""
        self.base_dir = base_dir
        self.page_size = page_size
        self.buffer_capacity = buffer_capacity
        self.counter = counter if counter is not None else DiskCounter()
        os.makedirs(base_dir, exist_ok=True)
        self.catalog = SchemaManager(base_dir, page_size=page_size, counter=self.counter)
        self._tables = {}
        self._indexes = {}

    # ---------- handles ----------

    def table_handle(self, name):
        """opens a table's file on first use and caches the handle for the rest of the session."""
        table = self.catalog.get_table(name)
        key = table.name.lower()
        if key not in self._tables:
            path = self.catalog.table_path(table.name)
            if table.organization == "SEQUENTIAL":
                handle = SequentialFile(path, table.schema, table.primary_key or table.columns[0].name,
                                        page_size=self.page_size, counter=self.counter,
                                        capacity=self.buffer_capacity)
            else:
                handle = HeapFile(path, table.schema, page_size=self.page_size,
                                  counter=self.counter, capacity=self.buffer_capacity)
            self._tables[key] = handle
        return self._tables[key]

    def index_handle(self, table_name, index_def):
        """opens an index file on first use and caches the handle."""
        table = self.catalog.get_table(table_name)
        key = (table.name.lower(), index_def.name.lower())
        if key not in self._indexes:
            column = table.schema.column(index_def.column)
            self._indexes[key] = INDEX_CLASSES[index_def.kind](
                self.catalog.index_path(table.name, index_def), column.dtype,
                page_size=self.page_size, counter=self.counter, capacity=self.buffer_capacity)
        return self._indexes[key]

    def indexes_of(self, table_name):
        """returns <definition, handle> for every index of a table, used to keep them in sync."""
        table = self.catalog.get_table(table_name)
        return [(index, self.index_handle(table.name, index)) for index in table.indexes]

    # ---------- DDL ----------

    def create_table(self, name, columns, organization="HEAP"):
        """registers a table in the catalog and creates its empty binary file."""
        table = TableDef(name, [Column(n, t, pk) for n, t, pk in columns], organization)
        if organization == "SEQUENTIAL" and table.primary_key is None:
            raise CatalogError("a SEQUENTIAL table needs a PRIMARY KEY to sort its main area by")
        self.catalog.create_table(table)
        self.table_handle(name)
        return table

    def drop_table(self, name):
        """closes and deletes a table's files along with the indexes built on it."""
        table = self.catalog.get_table(name)
        for index, handle in self.indexes_of(table.name):
            handle.close()
            self._indexes.pop((table.name.lower(), index.name.lower()), None)
        handle = self._tables.pop(table.name.lower(), None)
        if handle:
            handle.close()
        return self.catalog.drop_table(name)

    def create_index(self, name, table_name, column, kind="BTREE"):
        """registers an index and bulk-loads it from the records already in the table."""
        table = self.catalog.get_table(table_name)
        if table.organization != "HEAP":
            raise CatalogError(
                "indexes are only supported on HEAP tables: a SEQUENTIAL file moves records when it "
                "inserts in sorted position, so stored RIDs would not stay valid. Query it by its "
                "primary key instead and the planner will use binary search.")
        index_def = self.catalog.add_index(table.name, IndexDef(name, column, kind))
        index = self.index_handle(table.name, index_def)
        source = self.table_handle(table.name)
        position = table.schema.index_of(column)
        for rid, record in source.scan():
            index.insert(table.schema.unpack(record)[position], rid)
        index.flush()
        return index_def

    def drop_index(self, table_name, index_name):
        """closes an index file and removes it from the catalog."""
        table = self.catalog.get_table(table_name)
        key = (table.name.lower(), index_name.lower())
        handle = self._indexes.pop(key, None)
        if handle:
            handle.close()
        return self.catalog.drop_index(table.name, index_name)

    # ---------- DML ----------

    def insert(self, table_name, values):
        """packs a tuple, stores it and adds it to every index of the table."""
        table = self.catalog.get_table(table_name)
        record = table.schema.pack(values)
        handle = self.table_handle(table.name)
        location = handle.insert(record)
        if table.organization == "HEAP":
            for index_def, index in self.indexes_of(table.name):
                index.insert(table.schema.unpack(record)[table.schema.index_of(index_def.column)], location)
        return location

    def delete_rids(self, table_name, entries):
        """deletes located records and removes their keys from every index."""
        table = self.catalog.get_table(table_name)
        handle = self.table_handle(table.name)
        removed = 0
        for location, record in entries:
            values = table.schema.unpack(record)
            if table.organization == "HEAP":
                for index_def, index in self.indexes_of(table.name):
                    index.delete(values[table.schema.index_of(index_def.column)], location)
                removed += 1 if handle.delete(location) else 0
            else:
                removed += handle.delete(values[table.schema.index_of(handle.key_column)])
        return removed

    def reorganize(self, table_name):
        """rebuilds a sequential file's main area and empties its overflow."""
        table = self.catalog.get_table(table_name)
        if table.organization != "SEQUENTIAL":
            raise CatalogError(f"table {table.name!r} is a HEAP file and has no overflow area to reorganize")
        return self.table_handle(table.name).reorganize()

    # ---------- reporting ----------

    def table_info(self, table_def):
        """returns the metadata GET /api/tables exposes: columns, organization, indexes, size."""
        handle = self.table_handle(table_def.name)
        info = {
            "name": table_def.name,
            "organization": table_def.organization,
            "columns": [c.to_dict() for c in table_def.columns],
            "primary_key": table_def.primary_key,
            "indexes": [i.to_dict() for i in table_def.indexes],
            "records": handle.num_records,
            "pages": handle.num_pages,
            "page_size": self.page_size,
        }
        if table_def.organization == "SEQUENTIAL":
            info["main_pages"] = handle.num_main_pages
            info["overflow_pages"] = handle.overflow_pages()
        return info

    def flush(self):
        """writes every open table and index back to disk."""
        for handle in list(self._tables.values()) + list(self._indexes.values()):
            handle.flush()

    def close(self):
        """flushes and closes the catalog, every table and every index."""
        for handle in list(self._indexes.values()):
            handle.close()
        for handle in list(self._tables.values()):
            handle.close()
        self._indexes.clear()
        self._tables.clear()
        self.catalog.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __repr__(self):
        return f"Database({self.base_dir!r}, tables={len(self.catalog.tables)}, page_size={self.page_size})"
