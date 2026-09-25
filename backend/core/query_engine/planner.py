"""Reglas visibles de elección de ruta; los costos reportados se miden al ejecutar."""

from dataclasses import dataclass
from enum import Enum


class AccessPath(str, Enum):
    SEQ_SCAN = "SeqScan"
    INDEX_SCAN = "IndexScan"
    INDEX_RANGE_SCAN = "IndexRangeScan"


@dataclass
class QueryPlan:
    access_path: AccessPath
    index: object = None
    column: str = ""
    equality: object = None
    lower: object = None
    upper: object = None


class QueryPlanner:
    def __init__(self, schema_manager):
        self.schema_manager = schema_manager

    # PARTE IMPORTANTE PARA EXPOSICION: SELECCION DE RUTA DE ACCESO
    def choose_access_path(self, query):
        table = self.schema_manager.get_table(query.table)
        indexes = [i for i in table.indexes if not i.internal]
        for condition in query.conditions:
            if condition.operator == "=":
                applicable = [i for i in indexes if i.column == condition.column]
                if applicable:
                    index = next(
                        (i for i in applicable if i.kind == "HASH"), applicable[0]
                    )
                    return QueryPlan(
                        AccessPath.INDEX_SCAN, index, condition.column, condition.value
                    )
        for index in indexes:
            bounds = [c for c in query.conditions if c.column == index.column]
            lowers = [c.value for c in bounds if c.operator in (">", ">=")]
            uppers = [c.value for c in bounds if c.operator in ("<", "<=")]
            if index.kind == "BTREE" and (lowers or uppers):
                return QueryPlan(
                    AccessPath.INDEX_RANGE_SCAN,
                    index,
                    index.column,
                    lower=max(lowers) if lowers else None,
                    upper=min(uppers) if uppers else None,
                )
        return QueryPlan(AccessPath.SEQ_SCAN)
