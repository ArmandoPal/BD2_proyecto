"""
Catálogo del sistema.

Mantiene la metadata de tablas: nombre, columnas y tipos (INT, CHAR(n),
FLOAT), tipo de organización de archivo (HEAP | SEQUENTIAL), e índices
activos por columna (BTREE | HASH). El planificador (query_engine/planner.py)
consulta este catálogo para decidir la ruta de acceso.
"""

from dataclasses import dataclass, field


@dataclass
class ColumnDef:
    name: str
    dtype: str   # "INT", "CHAR(30)", "FLOAT"


@dataclass
class IndexDef:
    name: str
    column: str
    kind: str    # "BTREE" | "HASH"


@dataclass
class TableDef:
    name: str
    columns: list[ColumnDef]
    organization: str  # "HEAP" | "SEQUENTIAL"
    indexes: list[IndexDef] = field(default_factory=list)


class SchemaManager:
    def __init__(self):
        self.tables: dict[str, TableDef] = {}

    def create_table(self, table_def: TableDef) -> None:
        """TODO: registrar tabla, persistir catálogo en disco (no solo en memoria)."""
        raise NotImplementedError

    def get_table(self, name: str) -> TableDef:
        """TODO: retornar definición de tabla o lanzar error si no existe."""
        raise NotImplementedError

    def add_index(self, table_name: str, index_def: IndexDef) -> None:
        """TODO: registrar índice sobre una columna existente."""
        raise NotImplementedError
