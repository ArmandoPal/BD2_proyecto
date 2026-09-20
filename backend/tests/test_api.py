"""Tests for the REST layer: the three required endpoints and their error handling."""

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.main import app


@pytest.fixture
def client(tmp_path):
    """points the process-wide database at a temporary directory and yields a test client."""
    routes.close_database()
    routes.DATA_DIR = str(tmp_path / "db")
    routes.PAGE_SIZE = 1024
    routes.BUFFER_CAPACITY = 16
    with TestClient(app) as client:
        yield client
    routes.close_database()


def run(client, sql):
    """posts one statement to /api/query and returns the parsed payload."""
    response = client.post("/api/query", json={"sql": sql})
    assert response.status_code == 200, response.json()
    return response.json()


def test_health_reports_the_storage_configuration(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["page_size"] == 1024


def test_query_endpoint_returns_rows_and_metrics(client):
    run(client, "CREATE TABLE productos (id INT PRIMARY KEY, nombre CHAR(20), precio FLOAT) USING HEAP;")
    run(client, "INSERT INTO productos VALUES (1, 'laptop', 999.9), (2, 'mouse', 19.9);")
    payload = run(client, "SELECT * FROM productos WHERE id = 2;")

    assert payload["rows"] == [{"id": 2, "nombre": "mouse", "precio": 19.9}]
    assert payload["columns"] == ["id", "nombre", "precio"]
    assert payload["access_path"] == "SeqScan"
    assert payload["plan"]["estimated_reads"] >= 1

    metrics = payload["metrics"]
    assert set(metrics) == {"disk_reads", "disk_writes", "parse_time_ms", "exec_time_ms", "total_time_ms"}
    assert metrics["parse_time_ms"] > 0
    assert metrics["disk_reads"] == 0   # the only data page is still resident in the buffer pool


def test_a_cold_scan_reports_one_read_per_data_page(client):
    run(client, "CREATE TABLE t (id INT PRIMARY KEY, n CHAR(8)) USING HEAP;")
    for i in range(300):
        run(client, f"INSERT INTO t VALUES ({i}, 'n{i}');")

    database = routes.get_database()
    handle = database.table_handle("t")
    handle.pool.capacity = 1
    handle.pool.clear()

    payload = run(client, "SELECT * FROM t;")
    assert payload["row_count"] == 300
    assert payload["metrics"]["disk_reads"] == handle.num_data_pages


def test_plan_is_exposed_for_the_metrics_panel(client):
    run(client, "CREATE TABLE t (id INT PRIMARY KEY, n CHAR(8)) USING HEAP;")
    for i in range(200):
        run(client, f"INSERT INTO t VALUES ({i}, 'n{i}');")
    run(client, "CREATE INDEX idx ON t (id) USING BTREE;")
    plan = run(client, "SELECT * FROM t WHERE id = 100;")["plan"]
    assert plan["access_path"] == "IndexScan"
    assert plan["index_kind"] == "BTREE"
    assert "BTREE" in plan["reason"]


def test_tables_endpoint_lists_organization_and_indexes(client):
    run(client, "CREATE TABLE t (id INT PRIMARY KEY, n CHAR(8)) USING HEAP;")
    run(client, "INSERT INTO t VALUES (1, 'a');")
    run(client, "CREATE INDEX idx ON t (id) USING HASH;")

    table = client.get("/api/tables").json()["tables"][0]
    assert table["name"] == "t"
    assert table["organization"] == "HEAP"
    assert table["records"] == 1
    assert table["indexes"][0]["kind"] == "HASH"


def test_describe_table_returns_404_for_an_unknown_table(client):
    assert client.get("/api/tables/ghost").status_code == 404


def test_reorganize_endpoint_rebuilds_a_sequential_file(client):
    import random
    run(client, "CREATE TABLE t (id INT PRIMARY KEY, n CHAR(8)) USING SEQUENTIAL;")
    ids = list(range(400))
    random.Random(6).shuffle(ids)
    for i in ids:
        run(client, f"INSERT INTO t VALUES ({i}, 'n{i}');")
    assert client.get("/api/tables/t").json()["overflow_pages"] > 0

    payload = client.post("/api/tables/reorganize", json={"table_name": "t"}).json()
    assert payload["stats"]["records"] == 400
    assert payload["metrics"]["disk_writes"] > 0
    assert client.get("/api/tables/t").json()["overflow_pages"] == 0


def test_reorganizing_a_heap_table_is_a_client_error(client):
    run(client, "CREATE TABLE t (id INT PRIMARY KEY) USING HEAP;")
    assert client.post("/api/tables/reorganize", json={"table_name": "t"}).status_code == 400


def test_bad_sql_is_a_400_not_a_crash(client):
    for sql in ("SELECT * FROM ghost;", "SELEC * FROM t;", "CREATE TABLE t (id TEXT);"):
        response = client.post("/api/query", json={"sql": sql})
        assert response.status_code == 400
        assert response.json()["detail"]
