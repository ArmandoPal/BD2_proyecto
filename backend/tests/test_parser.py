import pytest
from backend.core.query_engine.parser import SQLParser


@pytest.mark.parametrize(
    "sql,kind",
    [
        (
            "CREATE TABLE t (id INT PRIMARY KEY, name CHAR(30), price FLOAT) USING HEAP;",
            "CREATE_TABLE",
        ),
        ("CREATE TABLE t (id INT PRIMARY KEY) USING SEQUENTIAL;", "CREATE_TABLE"),
        ("INSERT INTO t VALUES (1, 'O''Brien, Perú', -2.5e2);", "INSERT"),
        ("SELECT * FROM t WHERE id >= 1 AND id <= 20;", "SELECT"),
        ("DELETE FROM t WHERE id = 1;", "DELETE"),
        ("CREATE INDEX i ON t(id) USING BTREE;", "CREATE_INDEX"),
        ("CREATE INDEX i ON t(id) USING HASH;", "CREATE_INDEX"),
    ],
)
def test_supported_sql(sql, kind):
    assert SQLParser().parse(sql).kind == kind


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE t;",
        "SELECT * FROM t; DELETE FROM t WHERE id=1;",
        "INSERT INTO t VALUES ('unclosed);",
        "SELECT * FROM t WHERE id=1 OR id=2;",
        "SELECT * FROM t garbage",
        "DELETE FROM t;",
        "CREATE TABLE t(id DATE) USING HEAP;",
    ],
)
def test_invalid_sql(sql):
    with pytest.raises(ValueError):
        SQLParser().parse(sql)
