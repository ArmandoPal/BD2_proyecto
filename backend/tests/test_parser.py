"""Unit tests for the SQL lexer, parser and the planner's access-path rules."""

import pytest

from backend.query_engine.parser import (
    Comparison,
    CreateIndex,
    CreateTable,
    Delete,
    Insert,
    Predicate,
    Reorganize,
    Select,
    SQLParser,
    SQLSyntaxError,
    tokenize,
)


@pytest.fixture
def parser():
    """a fresh parser per test."""
    return SQLParser()


# ---------- lexer ----------

def test_keywords_are_recognized_case_insensitively():
    kinds = [(t.kind, t.value) for t in tokenize("select * from t")]
    assert ("KEYWORD", "SELECT") in kinds and ("KEYWORD", "FROM") in kinds


def test_comments_and_whitespace_are_dropped():
    assert [t.value for t in tokenize("SELECT -- comment\n *")][:2] == ["SELECT", "*"]


def test_escaped_quotes_inside_strings_are_handled():
    (token, _) = tokenize("'O''Brien'")
    assert token.kind == "STRING"


def test_unknown_character_is_reported_with_its_position():
    with pytest.raises(SQLSyntaxError) as error:
        tokenize("SELECT # FROM t")
    assert "position 7" in str(error.value)


# ---------- statements ----------

def test_create_table_reads_types_primary_key_and_engine(parser):
    statement = parser.parse(
        "CREATE TABLE empleados (id INT PRIMARY KEY, nombre CHAR(30), salario FLOAT) USING SEQUENTIAL;")
    assert isinstance(statement, CreateTable)
    assert statement.columns == [("id", "INT", True), ("nombre", "CHAR(30)", False), ("salario", "FLOAT", False)]
    assert statement.organization == "SEQUENTIAL"


def test_create_table_defaults_to_heap(parser):
    assert parser.parse("CREATE TABLE t (id INT);").organization == "HEAP"


def test_unknown_storage_engine_is_rejected(parser):
    with pytest.raises(SQLSyntaxError):
        parser.parse("CREATE TABLE t (id INT) USING COLUMNAR;")


def test_unknown_column_type_is_rejected(parser):
    with pytest.raises(SQLSyntaxError):
        parser.parse("CREATE TABLE t (id TEXT);")


def test_insert_accepts_several_tuples(parser):
    statement = parser.parse("INSERT INTO t VALUES (1, 'a', 1.5), (2, 'b', 2.5);")
    assert isinstance(statement, Insert)
    assert statement.rows == [[1, "a", 1.5], [2, "b", 2.5]]


def test_insert_with_an_explicit_column_list(parser):
    statement = parser.parse("INSERT INTO t (id, nombre) VALUES (1, 'ada');")
    assert statement.columns == ["id", "nombre"]


def test_create_index_reads_the_structure(parser):
    statement = parser.parse("CREATE INDEX idx ON t (id) USING HASH;")
    assert isinstance(statement, CreateIndex)
    assert (statement.column, statement.index_kind) == ("id", "HASH")


def test_create_index_defaults_to_btree(parser):
    assert parser.parse("CREATE INDEX idx ON t (id);").index_kind == "BTREE"


def test_select_star_has_no_projection_list(parser):
    statement = parser.parse("SELECT * FROM t;")
    assert isinstance(statement, Select)
    assert statement.columns is None and statement.predicate.is_empty()


def test_select_with_an_equality_predicate(parser):
    predicate = parser.parse("SELECT * FROM t WHERE id = 101;").predicate
    assert predicate.bounds_for("id") == (101, None, None)


def test_select_with_a_range_predicate(parser):
    predicate = parser.parse("SELECT * FROM t WHERE id >= 100 AND id <= 500;").predicate
    assert predicate.bounds_for("id") == (None, 100, 500)


def test_between_expands_into_two_bounds(parser):
    predicate = parser.parse("SELECT * FROM t WHERE salario BETWEEN 1000 AND 2000;").predicate
    assert len(predicate.terms) == 2
    assert predicate.bounds_for("salario") == (None, 1000, 2000)


def test_delete_and_reorganize_are_parsed(parser):
    assert isinstance(parser.parse("DELETE FROM t WHERE id = 1;"), Delete)
    assert isinstance(parser.parse("REORGANIZE TABLE t;"), Reorganize)


def test_semicolon_is_optional(parser):
    assert isinstance(parser.parse("SELECT * FROM t"), Select)


def test_trailing_garbage_is_rejected(parser):
    with pytest.raises(SQLSyntaxError):
        parser.parse("SELECT * FROM t; DROP TABLE t;")


def test_unsupported_statement_is_rejected(parser):
    with pytest.raises(SQLSyntaxError):
        parser.parse("UPDATE t SET id = 1;")


def test_parse_time_is_measured(parser):
    parser.parse("SELECT * FROM t WHERE id = 1;")
    assert parser.parse_time_ms > 0


# ---------- predicate helpers ----------

def test_comparison_evaluates_every_operator():
    assert Comparison("id", "=", 5).matches(5)
    assert Comparison("id", "<>", 5).matches(6)
    assert Comparison("id", ">=", 5).matches(5)
    assert not Comparison("id", "<", 5).matches(5)


def test_tightest_bounds_win_when_a_column_is_constrained_twice():
    predicate = Predicate([Comparison("id", ">=", 10), Comparison("id", ">=", 50),
                           Comparison("id", "<=", 900), Comparison("id", "<=", 100)])
    assert predicate.bounds_for("id") == (None, 50, 100)
