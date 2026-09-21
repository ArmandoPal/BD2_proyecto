"""Catálogo JSON: únicamente esquemas y nombres, nunca registros de tablas."""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from backend.core.storage.record_serializer import RecordSerializer


def identifier(name):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Identificador inválido: {name}")
    return name.lower()


@dataclass
class ColumnDef:
    name: str
    dtype: str
    primary_key: bool = False


@dataclass
class IndexDef:
    name: str
    column: str
    kind: str
    filename: str = ""
    internal: bool = False


@dataclass
class TableDef:
    name: str
    columns: list[ColumnDef]
    organization: str
    indexes: list[IndexDef] = field(default_factory=list)
    filename: str = ""
    page_size: int = 4096

    @property
    def primary_key(self):
        return next(c.name for c in self.columns if c.primary_key)

    def column(self, name):
        for column in self.columns:
            if column.name == name.lower():
                return column
        raise ValueError(f"Columna inexistente: {name}")


class SchemaManager:
    def __init__(self, directory="data/database"):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "catalog.json"
        self.tables = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("version") != 1:
                raise ValueError("Versión de catálogo incompatible")
            for item in raw["tables"]:
                item["columns"] = [ColumnDef(**c) for c in item["columns"]]
                item["indexes"] = [IndexDef(**i) for i in item["indexes"]]
                table = TableDef(**item)
                self.validate(table)
                for filename in [table.filename] + [i.filename for i in table.indexes]:
                    if Path(filename).name != filename:
                        raise ValueError("Ruta de catálogo inválida")
                self.tables[table.name] = table

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"version": 1, "tables": [asdict(t) for t in self.tables.values()]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def validate(self, table):
        identifier(table.name)
        names = [identifier(c.name) for c in table.columns]
        if (
            len(set(names)) != len(names)
            or sum(c.primary_key for c in table.columns) != 1
        ):
            raise ValueError(
                "Se requiere exactamente una PRIMARY KEY y columnas sin repetir"
            )
        if table.organization not in ("HEAP", "SEQUENTIAL"):
            raise ValueError("Organización no soportada")
        RecordSerializer(table.columns)

    def create_table(self, table):
        self.validate(table)
        if table.name in self.tables:
            raise ValueError(f"Tabla existente: {table.name}")
        self.tables[table.name] = table
        self.save()

    def get_table(self, name):
        name = identifier(name)
        if name not in self.tables:
            raise ValueError(f"Tabla inexistente: {name}")
        return self.tables[name]

    def drop_table(self, name):
        table = self.get_table(name)
        filenames = [table.filename]
        if table.organization == "SEQUENTIAL":
            filenames.append(table.filename + ".overflow")
        for index in table.indexes:
            filenames.append(index.filename)
            if index.kind == "HASH":
                filenames.append(index.filename + ".dir")
        # Archivos exactos del catálogo: nunca borrar por prefijo o comodín.
        for filename in filenames:
            (self.directory / filename).unlink(missing_ok=True)
        del self.tables[table.name]
        self.save()

    def check_index_name(self, name):
        identifier(name)
        if any(i.name == name for t in self.tables.values() for i in t.indexes):
            raise ValueError(f"Índice existente: {name}")

    def add_index(self, table_name, index):
        self.check_index_name(index.name)
        table = self.get_table(table_name)
        table.column(index.column)
        table.indexes.append(index)
        self.save()
