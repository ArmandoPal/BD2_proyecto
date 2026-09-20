"""System catalog: the metadata the planner reads before choosing an access path.

Stores, for every table, its column layout, its file organization
(``HEAP`` | ``SEQUENTIAL``) and the indexes built on it (``BTREE`` | ``HASH``).

The catalog is persisted like any other relation: as JSON records inside pages
of a binary file reached through :class:`DiskManager`, never with pickle and
never with a global ``.read()``. It is small and rarely written, so a change
rewrites the whole file instead of maintaining a free-list.
"""

import json
import os

from backend.storage import BufferPool, DiskManager, Page, PageType

from .record import Column, Schema

CATALOG_FILENAME = "_catalog.dat"
ORGANIZATIONS = ("HEAP", "SEQUENTIAL")
INDEX_KINDS = ("BTREE", "HASH")


class CatalogError(Exception):
    """raised when a table or index is missing, duplicated or declared with a bad option."""


class IndexDef:
    """one index: its name, the column it covers and the structure backing it."""

    __slots__ = ("name", "column", "kind")

    def __init__(self, name, column, kind):
        """validates the index kind so an unsupported structure fails at creation, not at query time."""
        kind = str(kind).upper()
        if kind not in INDEX_KINDS:
            raise CatalogError(f"index kind must be one of {INDEX_KINDS}, got {kind!r}")
        self.name = name
        self.column = column
        self.kind = kind

    def to_dict(self):
        """returns a json-friendly view for persistence."""
        return {"name": self.name, "column": self.column, "kind": self.kind}

    @classmethod
    def from_dict(cls, data):
        """rebuilds an index definition from the dict written by to_dict()."""
        return cls(data["name"], data["column"], data["kind"])

    def __repr__(self):
        return f"IndexDef({self.name} on {self.column} USING {self.kind})"


class TableDef:
    """one table: its columns, how its records are organized on disk and its indexes."""

    __slots__ = ("name", "columns", "organization", "indexes")

    def __init__(self, name, columns, organization="HEAP", indexes=None):
        """validates the organization and keeps the column list in declaration order."""
        organization = str(organization).upper()
        if organization not in ORGANIZATIONS:
            raise CatalogError(f"organization must be one of {ORGANIZATIONS}, got {organization!r}")
        self.name = name
        self.columns = list(columns)
        self.organization = organization
        self.indexes = list(indexes or [])

    @property
    def schema(self):
        """builds the record layout used to pack and unpack this table's tuples."""
        return Schema(self.columns)

    @property
    def primary_key(self):
        """returns the primary key column name, or None when the table declares none."""
        column = self.schema.primary_key
        return column.name if column else None

    def index_on(self, column_name, kind=None):
        """finds an index covering a column, optionally restricted to one structure."""
        for index in self.indexes:
            if index.column.lower() == column_name.lower() and (kind is None or index.kind == kind):
                return index
        return None

    def to_dict(self):
        """returns a json-friendly view of the whole table definition."""
        return {
            "name": self.name,
            "organization": self.organization,
            "columns": [c.to_dict() for c in self.columns],
            "indexes": [i.to_dict() for i in self.indexes],
        }

    @classmethod
    def from_dict(cls, data):
        """rebuilds a table definition from the dict written by to_dict()."""
        return cls(
            data["name"],
            [Column.from_dict(c) for c in data["columns"]],
            data.get("organization", "HEAP"),
            [IndexDef.from_dict(i) for i in data.get("indexes", [])],
        )

    def __repr__(self):
        return f"TableDef({self.name} USING {self.organization}, {len(self.columns)} cols, {len(self.indexes)} idx)"


class SchemaManager:
    """keeps table metadata in memory and mirrors it into a paged catalog file on every change."""

    def __init__(self, base_dir, page_size=4096, counter=None):
        """creates the data directory if needed and loads whatever the catalog already holds."""
        self.base_dir = base_dir
        self.page_size = page_size
        os.makedirs(base_dir, exist_ok=True)
        self.disk = DiskManager(os.path.join(base_dir, CATALOG_FILENAME),
                                page_size=page_size, counter=counter)
        self.pool = BufferPool(self.disk, capacity=8)
        self.tables = {}
        self._load()

    # ---------- persistence ----------

    def _load(self):
        """reads every catalog page and rebuilds the in-memory table dictionary."""
        self.tables = {}
        for page_id in range(self.disk.num_pages()):
            page = Page.from_bytes(self.disk.read_page(page_id), self.page_size)
            for _, raw in page.iter_records():
                table = TableDef.from_dict(json.loads(raw.decode("utf-8")))
                self.tables[table.name.lower()] = table

    def _persist(self):
        """rewrites the whole catalog file, packing definitions into as few pages as needed."""
        blobs = [json.dumps(t.to_dict(), separators=(",", ":")).encode("utf-8")
                 for t in self.tables.values()]
        for page_id in range(self.disk.num_pages()):
            self.pool.discard(page_id)
        self.disk.truncate(0)

        page = Page(self.disk.allocate_page(PageType.CATALOG), self.page_size, PageType.CATALOG)
        for blob in blobs:
            if not page.can_fit(len(blob)):
                self.disk.write_page(page.page_id, page.to_bytes())
                page = Page(self.disk.allocate_page(PageType.CATALOG), self.page_size, PageType.CATALOG)
            page.insert_record(blob)
        self.disk.write_page(page.page_id, page.to_bytes())

    # ---------- table metadata ----------

    def create_table(self, table_def):
        """registers a new table and writes the catalog back to disk."""
        key = table_def.name.lower()
        if key in self.tables:
            raise CatalogError(f"table {table_def.name!r} already exists")
        table_def.schema  # validates the layout before anything is persisted
        self.tables[key] = table_def
        self._persist()
        return table_def

    def get_table(self, name):
        """returns a table definition or fails with a clear error when it is unknown."""
        try:
            return self.tables[name.lower()]
        except KeyError:
            raise CatalogError(f"table {name!r} does not exist") from None

    def has_table(self, name):
        """true when the catalog knows a table by that name."""
        return name.lower() in self.tables

    def drop_table(self, name):
        """removes a table from the catalog and deletes the binary files that backed it."""
        table = self.get_table(name)
        for path in self.files_of(table):
            if os.path.exists(path):
                os.remove(path)
        del self.tables[name.lower()]
        self._persist()
        return table

    def list_tables(self):
        """returns every table definition, used by GET /api/tables."""
        return list(self.tables.values())

    def add_index(self, table_name, index_def):
        """attaches an index to an existing column and persists the change."""
        table = self.get_table(table_name)
        if index_def.column.lower() not in {c.name.lower() for c in table.columns}:
            raise CatalogError(f"column {index_def.column!r} does not exist in {table_name!r}")
        if any(i.name.lower() == index_def.name.lower() for i in table.indexes):
            raise CatalogError(f"index {index_def.name!r} already exists")
        if table.index_on(index_def.column, index_def.kind):
            raise CatalogError(f"a {index_def.kind} index already covers {index_def.column!r}")
        table.indexes.append(index_def)
        self._persist()
        return index_def

    def drop_index(self, table_name, index_name):
        """detaches an index from a table and removes its file."""
        table = self.get_table(table_name)
        for position, index in enumerate(table.indexes):
            if index.name.lower() == index_name.lower():
                path = self.index_path(table.name, index)
                for candidate in (path, path + ".dir", path + ".ovf"):
                    if os.path.exists(candidate):
                        os.remove(candidate)
                table.indexes.pop(position)
                self._persist()
                return index
        raise CatalogError(f"index {index_name!r} does not exist on {table_name!r}")

    # ---------- file naming ----------

    def table_path(self, name):
        """returns the binary file that stores a table's records."""
        return os.path.join(self.base_dir, f"{name.lower()}.dat")

    def index_path(self, table_name, index_def):
        """returns the binary file that stores one index of a table."""
        return os.path.join(self.base_dir, f"{table_name.lower()}_{index_def.name.lower()}.idx")

    def files_of(self, table_def):
        """lists every file belonging to a table, so dropping it leaves nothing behind."""
        paths = [self.table_path(table_def.name)]
        root, _ = os.path.splitext(paths[0])
        paths.append(root + ".ovf")
        for index in table_def.indexes:
            base = self.index_path(table_def.name, index)
            paths.extend([base, base + ".dir"])
        return paths

    def close(self):
        """flushes the catalog and closes its file."""
        self.pool.flush_all()
        self.disk.close()

    def __repr__(self):
        return f"SchemaManager({self.base_dir!r}, tables={len(self.tables)})"
