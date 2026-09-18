"""
Planificador de Consultas (3.4 Motor de Consultas y Parser SQL)

Regla de decisión sobre la cláusula WHERE:
    - Igualdad + índice BTREE o HASH aplicable -> IndexScan
    - Rango + índice BTREE aplicable           -> IndexRangeScan
    - En cualquier otro caso                   -> SeqScan
"""

from enum import Enum


class AccessPath(Enum):
    SEQ_SCAN = "SeqScan"
    INDEX_SCAN = "IndexScan"
    INDEX_RANGE_SCAN = "IndexRangeScan"


class QueryPlanner:
    def __init__(self, schema_manager):
        self.schema_manager = schema_manager

    def choose_access_path(self, parsed_query) -> AccessPath:
        """TODO: inspeccionar WHERE + catálogo de índices, elegir ruta óptima."""
        raise NotImplementedError
