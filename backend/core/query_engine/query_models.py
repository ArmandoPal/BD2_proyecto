"""Representación pequeña y explícita de las sentencias SQL soportadas."""

from dataclasses import dataclass, field


@dataclass
class Condition:
    column: str
    operator: str
    value: object


@dataclass
class ParsedQuery:
    kind: str
    table: str
    columns: list = field(default_factory=list)
    organization: str = "HEAP"
    values: list = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    projection: list[str] = field(default_factory=lambda: ["*"])
    index_name: str = ""
    index_kind: str = ""
    index_column: str = ""
