"""
Parser SQL básico (3.4 Motor de Consultas y Parser SQL)

Debe interpretar:
    CREATE TABLE t (col TIPO, ...) USING [HEAP | SEQUENTIAL];
    INSERT INTO t VALUES (...);
    CREATE INDEX idx ON t (col) USING [BTREE | HASH];
    SELECT * FROM t WHERE col = valor;
    SELECT * FROM t WHERE col >= v1 AND col <= v2;
    DELETE FROM t WHERE col = valor;

Puede implementarse con una gramática simple (regex/tokenizer manual) o
con una librería de parsing (ej. sly, lark) — no está prohibido, a
diferencia del motor de almacenamiento.
"""


class ParsedQuery:
    """TODO: representación intermedia del AST/comando parseado."""
    pass


class SQLParser:
    def parse(self, sql: str) -> ParsedQuery:
        """TODO: tokenizar y construir el ParsedQuery correspondiente."""
        raise NotImplementedError
