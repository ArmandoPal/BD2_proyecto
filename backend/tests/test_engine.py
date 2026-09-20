"""End-to-end tests: SQL in, tuples and I/O telemetry out, across both file organizations."""

import pytest

from backend.catalog.schema_manager import CatalogError
from backend.query_engine import Database, QueryExecutor

PRODUCTS = ("CREATE TABLE productos (id INT PRIMARY KEY, nombre CHAR(24), "
            "precio FLOAT, stock INT) USING {engine};")


@pytest.fixture
def heap_db(tmp_path):
    """a heap-backed products table loaded with 3000 rows."""
    database = Database(str(tmp_path / "db"), page_size=1024, buffer_capacity=16)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="HEAP"))
    for i in range(3000):
        database.insert("productos", [i, f"prod-{i}", i * 1.25, i % 50])
    yield database, executor
    database.close()


def test_create_insert_and_select_roundtrip(tmp_path):
    database = Database(str(tmp_path / "db"), page_size=1024)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="HEAP"))
    executor.execute("INSERT INTO productos VALUES (1, 'laptop', 999.9, 5), (2, 'mouse', 19.9, 80);")
    result = executor.execute("SELECT * FROM productos;")
    assert result.row_count == 2
    assert result.rows[0] == {"id": 1, "nombre": "laptop", "precio": 999.9, "stock": 5}
    database.close()


def test_projection_returns_only_the_asked_columns(heap_db):
    _, executor = heap_db
    row = executor.execute("SELECT id, precio FROM productos WHERE id = 7;").rows[0]
    assert set(row) == {"id", "precio"}


def test_full_scan_is_chosen_without_an_index(heap_db):
    _, executor = heap_db
    result = executor.execute("SELECT * FROM productos WHERE id = 1500;")
    assert result.access_path == "SeqScan"
    assert result.row_count == 1


def test_hash_index_turns_equality_into_a_constant_cost_lookup(heap_db):
    database, executor = heap_db
    executor.execute("CREATE INDEX idx_id ON productos (id) USING HASH;")
    scan = executor.execute("SELECT * FROM productos WHERE id = 2500;")
    assert scan.access_path == "IndexScan"
    assert scan.rows[0]["id"] == 2500
    assert scan.disk_reads < database.table_handle("productos").num_data_pages


def test_btree_index_serves_both_equality_and_ranges(heap_db):
    _, executor = heap_db
    executor.execute("CREATE INDEX idx_id ON productos (id) USING BTREE;")
    point = executor.execute("SELECT * FROM productos WHERE id = 900;")
    narrow = executor.execute("SELECT * FROM productos WHERE id >= 100 AND id <= 110;")
    assert point.access_path == "IndexScan"
    assert narrow.access_path == "IndexRangeScan"
    assert [row["id"] for row in narrow.rows] == list(range(100, 111))


def test_planner_abandons_the_index_when_the_range_is_too_wide(heap_db):
    _, executor = heap_db
    executor.execute("CREATE INDEX idx_id ON productos (id) USING BTREE;")
    wide = executor.execute("SELECT * FROM productos WHERE id >= 0 AND id <= 2999;")
    assert wide.access_path == "SeqScan"
    assert "full scan wins" in wide.plan["reason"]
    assert wide.row_count == 3000


def test_every_result_carries_io_and_timing_telemetry(heap_db):
    _, executor = heap_db
    payload = executor.execute("SELECT * FROM productos WHERE id = 10;").to_dict()
    metrics = payload["metrics"]
    assert set(metrics) == {"disk_reads", "disk_writes", "parse_time_ms", "exec_time_ms", "total_time_ms"}
    assert metrics["disk_reads"] > 0 and metrics["parse_time_ms"] > 0


def test_delete_also_removes_the_key_from_every_index(heap_db):
    database, executor = heap_db
    executor.execute("CREATE INDEX idx_id ON productos (id) USING BTREE;")
    executor.execute("DELETE FROM productos WHERE id = 1234;")
    assert executor.execute("SELECT * FROM productos WHERE id = 1234;").row_count == 0
    assert database.index_handle("productos", database.catalog.get_table("productos").indexes[0]).search(1234) == []


def test_residual_predicate_is_applied_on_top_of_the_index(heap_db):
    _, executor = heap_db
    executor.execute("CREATE INDEX idx_stock ON productos (stock) USING HASH;")
    result = executor.execute("SELECT * FROM productos WHERE stock = 7 AND id <= 500;")
    assert result.access_path == "IndexScan"
    assert all(row["stock"] == 7 and row["id"] <= 500 for row in result.rows)


def test_sequential_table_uses_binary_search_on_its_key(tmp_path):
    database = Database(str(tmp_path / "db"), page_size=1024, buffer_capacity=16)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="SEQUENTIAL"))
    for i in range(2000):
        database.insert("productos", [i, f"prod-{i}", i * 1.25, i % 50])
    result = executor.execute("SELECT * FROM productos WHERE id = 1750;")
    assert result.access_path == "BinarySearchScan"
    assert result.rows[0]["nombre"] == "prod-1750"
    database.close()


def test_reorganize_empties_the_overflow_area(tmp_path):
    import random
    database = Database(str(tmp_path / "db"), page_size=1024, buffer_capacity=16)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="SEQUENTIAL"))
    ids = list(range(1500))
    random.Random(4).shuffle(ids)
    for i in ids:
        database.insert("productos", [i, f"prod-{i}", i * 1.25, i % 50])
    assert database.table_handle("productos").overflow_pages() > 0

    executor.execute("REORGANIZE TABLE productos;")
    assert database.table_handle("productos").overflow_pages() == 0
    assert executor.execute("SELECT * FROM productos WHERE id = 1499;").row_count == 1
    database.close()


def test_sequential_tables_reject_indexes_with_an_explanation(tmp_path):
    database = Database(str(tmp_path / "db"), page_size=1024)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="SEQUENTIAL"))
    with pytest.raises(CatalogError) as error:
        executor.execute("CREATE INDEX idx ON productos (id) USING BTREE;")
    assert "HEAP" in str(error.value)
    database.close()


def test_heap_tables_reject_reorganize(heap_db):
    _, executor = heap_db
    with pytest.raises(CatalogError):
        executor.execute("REORGANIZE TABLE productos;")


def test_database_state_survives_a_restart(tmp_path):
    path = str(tmp_path / "db")
    database = Database(path, page_size=1024)
    executor = QueryExecutor(database)
    executor.execute(PRODUCTS.format(engine="HEAP"))
    for i in range(600):
        database.insert("productos", [i, f"prod-{i}", i * 1.0, i % 7])
    executor.execute("CREATE INDEX idx_id ON productos (id) USING BTREE;")
    database.close()

    reopened = Database(path, page_size=1024)
    again = QueryExecutor(reopened)
    result = again.execute("SELECT * FROM productos WHERE id = 599;")
    assert result.access_path == "IndexScan"
    assert result.rows[0]["nombre"] == "prod-599"
    reopened.close()


def test_block_size_changes_the_page_count_not_the_answer(tmp_path):
    answers, pages = [], []
    for page_size in (1024, 4096):
        database = Database(str(tmp_path / f"db{page_size}"), page_size=page_size)
        executor = QueryExecutor(database)
        executor.execute(PRODUCTS.format(engine="HEAP"))
        for i in range(1200):
            database.insert("productos", [i, f"prod-{i}", i * 1.0, i % 7])
        answers.append(executor.execute("SELECT * FROM productos WHERE id = 1199;").rows)
        pages.append(database.table_handle("productos").num_data_pages)
        database.close()
    assert answers[0] == answers[1]
    assert pages[0] > pages[1]
