"""Tuple <-> bytes serialization with ``struct``.

Supported SQL types are fixed width, so a record has a constant size and a page
can hold a predictable number of them::

    INT       -> 'i'    4 bytes
    FLOAT     -> 'd'    8 bytes
    BOOL      -> '?'    1 byte
    CHAR(n)   -> 'ns'   n bytes, right-padded with NUL

A RID is packed as ``<page_id: u32, slot: u16>`` and is what index leaves store.
"""

import re
import struct

SCALAR_FORMATS = {"INT": "i", "FLOAT": "d", "BOOL": "?"}
CHAR_PATTERN = re.compile(r"^CHAR\s*\(\s*(\d+)\s*\)$", re.IGNORECASE)

RID_FORMAT = "<IH"
RID_SIZE = struct.calcsize(RID_FORMAT)


class TypeError_(ValueError):
    """raised when a column type is not one the engine can lay out on a page."""


def normalize_type(spec):
    """uppercases and trims a declared type so 'char( 30 )' and 'CHAR(30)' compare equal."""
    spec = " ".join(str(spec).split()).upper()
    match = CHAR_PATTERN.match(spec)
    if match:
        return f"CHAR({int(match.group(1))})"
    if spec in SCALAR_FORMATS:
        return spec
    raise TypeError_(f"unsupported column type: {spec!r}")


def type_format(spec):
    """maps a normalized type to its struct code, expanding CHAR(n) into 'ns'."""
    spec = normalize_type(spec)
    match = CHAR_PATTERN.match(spec)
    if match:
        return f"{int(match.group(1))}s"
    return SCALAR_FORMATS[spec]


def type_size(spec):
    """returns how many bytes one value of this type occupies on a page."""
    return struct.calcsize("<" + type_format(spec))


def make_coercer(spec):
    """builds, once per column, the function that converts a value into what the struct code expects."""
    spec = normalize_type(spec)
    if spec == "INT":
        return int
    if spec == "FLOAT":
        return float
    if spec == "BOOL":
        return bool
    width = int(CHAR_PATTERN.match(spec).group(1))

    def to_bytes(value):
        """encodes a string to utf-8 and truncates it to the declared width."""
        return str(value).encode("utf-8")[:width]
    return to_bytes


def make_decoder(spec):
    """builds, once per column, the function that turns an unpacked value back into a python value."""
    if normalize_type(spec).startswith("CHAR"):
        return lambda value: value.rstrip(b"\x00").decode("utf-8", errors="replace")
    return lambda value: value


def coerce(spec, value):
    """converts a python value into the exact type the struct code expects."""
    spec = normalize_type(spec)
    if spec == "INT":
        return int(value)
    if spec == "FLOAT":
        return float(value)
    if spec == "BOOL":
        return bool(value)
    width = int(CHAR_PATTERN.match(spec).group(1))
    raw = str(value).encode("utf-8")[:width]
    return raw


def decode(spec, value):
    """turns an unpacked struct value back into a plain python value, trimming CHAR padding."""
    if normalize_type(spec).startswith("CHAR"):
        return value.rstrip(b"\x00").decode("utf-8", errors="replace")
    return value


_VALUE_CODECS = {}


def value_codec(spec):
    """returns and caches the <struct, coercer, decoder> triple for a single-column type."""
    spec = normalize_type(spec)
    codec = _VALUE_CODECS.get(spec)
    if codec is None:
        codec = (struct.Struct("<" + type_format(spec)), make_coercer(spec), make_decoder(spec))
        _VALUE_CODECS[spec] = codec
    return codec


def pack_value(spec, value):
    """packs a single value, used for index keys where only one column matters."""
    packer, to_storage, _ = value_codec(spec)
    return packer.pack(to_storage(value))


def unpack_value(spec, raw):
    """unpacks a single value packed by pack_value()."""
    packer, _, from_storage = value_codec(spec)
    (value,) = packer.unpack(raw)
    return from_storage(value)


def pack_rid(rid):
    """packs a <page_id, slot> pair into the 6 bytes stored next to an index key."""
    return struct.pack(RID_FORMAT, rid[0], rid[1])


def unpack_rid(raw):
    """unpacks the 6-byte RID written by pack_rid()."""
    return tuple(struct.unpack(RID_FORMAT, raw))


class Column:
    """one column of a table: its name, its fixed-width type and whether it is the primary key."""

    __slots__ = ("name", "dtype", "primary_key")

    def __init__(self, name, dtype, primary_key=False):
        """normalizes the declared type so the layout is decided once, at creation time."""
        self.name = name
        self.dtype = normalize_type(dtype)
        self.primary_key = bool(primary_key)

    @property
    def size(self):
        """byte width of this column inside a record."""
        return type_size(self.dtype)

    def to_dict(self):
        """returns a json-friendly view, used when the catalog is persisted."""
        return {"name": self.name, "dtype": self.dtype, "primary_key": self.primary_key}

    @classmethod
    def from_dict(cls, data):
        """rebuilds a column from the dict written by to_dict()."""
        return cls(data["name"], data["dtype"], data.get("primary_key", False))

    def __repr__(self):
        pk = " PRIMARY KEY" if self.primary_key else ""
        return f"Column({self.name} {self.dtype}{pk})"


class Schema:
    """fixed-width record layout: builds one struct format for the whole tuple."""

    def __init__(self, columns):
        """precomputes the struct format and the record size from the column list."""
        if not columns:
            raise ValueError("a table needs at least one column")
        self.columns = list(columns)
        self.format = "<" + "".join(type_format(c.dtype) for c in self.columns)
        self._struct = struct.Struct(self.format)
        self._coercers = [make_coercer(c.dtype) for c in self.columns]
        self._decoders = [make_decoder(c.dtype) for c in self.columns]
        self.record_size = self._struct.size
        self._by_name = {c.name.lower(): i for i, c in enumerate(self.columns)}
        if len(self._by_name) != len(self.columns):
            raise ValueError("duplicate column names")

    @property
    def names(self):
        """column names in declaration order, which is also the order of a packed record."""
        return [c.name for c in self.columns]

    @property
    def primary_key(self):
        """returns the primary key column, or None when the table has none."""
        for column in self.columns:
            if column.primary_key:
                return column
        return None

    def index_of(self, name):
        """resolves a column name to its position, case-insensitively."""
        try:
            return self._by_name[name.lower()]
        except KeyError:
            raise KeyError(f"unknown column {name!r}") from None

    def column(self, name):
        """returns the Column object for a name."""
        return self.columns[self.index_of(name)]

    def pack(self, values):
        """coerces every value to its column type and packs the tuple into a fixed-size record."""
        if len(values) != len(self.columns):
            raise ValueError(f"expected {len(self.columns)} values, got {len(values)}")
        return self._struct.pack(*[to_storage(v) for to_storage, v in zip(self._coercers, values)])

    def unpack(self, raw):
        """unpacks a record back into a list of python values, trimming CHAR padding."""
        values = self._struct.unpack(raw[:self.record_size])
        return [from_storage(v) for from_storage, v in zip(self._decoders, values)]

    def to_row(self, raw):
        """unpacks a record straight into a name -> value dict for the API layer."""
        return dict(zip(self.names, self.unpack(raw)))

    def key_of(self, raw, column_name):
        """extracts a single column value from a packed record without materializing the whole row."""
        return self.unpack(raw)[self.index_of(column_name)]

    def records_per_page(self, page_size, header_size, slot_size):
        """estimates the blocking factor, used by the planner to predict page counts."""
        return max(1, (page_size - header_size) // (self.record_size + slot_size))

    def to_dict(self):
        """returns a json-friendly view of the layout for catalog persistence."""
        return {"columns": [c.to_dict() for c in self.columns]}

    @classmethod
    def from_dict(cls, data):
        """rebuilds a schema from the dict written by to_dict()."""
        return cls([Column.from_dict(c) for c in data["columns"]])

    def __repr__(self):
        return f"Schema({', '.join(f'{c.name}:{c.dtype}' for c in self.columns)}, size={self.record_size})"
