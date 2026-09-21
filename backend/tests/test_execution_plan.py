import pytest
from fastapi.testclient import TestClient

from backend.core.query_engine.executor import QueryExecutor
from backend.main import create_app


def setup_table(directory, organization="HEAP"):
    engine = QueryExecutor(directory=directory)
    engine.execute(f"CREATE TABLE t(id INT PRIMARY KEY, price INT) USING {organization};")
    for i in range(10):
        engine.execute(f"INSERT INTO t VALUES ({i}, {i});")
    return engine


def operators(plan):
    return [step["operator"] for step in plan["steps"]]


def test_actual_full_scan_counts_and_pagination(tmp_path):
    engine = setup_table(tmp_path)
    result = engine.execute("SELECT id FROM t WHERE price > 2;", offset=2, limit=3)
    plan = result.execution_plan
    assert plan["mode"] == "actual"
    assert operators(plan) == ["FullScan", "Filter", "Project", "Result"]
    assert [s["actual_rows"] for s in plan["steps"]] == [10, 7, 7, 3]
    assert plan["metrics"]["disk_reads"] == result.disk_reads
    assert plan["metrics"]["exec_time_ms"] == result.exec_time_ms
    assert plan["metrics"]["disk_writes"] == 0


def test_index_plan_and_filter_counts(tmp_path):
    engine = setup_table(tmp_path)
    engine.execute("CREATE INDEX b ON t(id) USING BTREE;")
    result = engine.execute("SELECT * FROM t WHERE id >= 2 AND id <= 8 AND price != 4;")
    assert operators(result.execution_plan) == ["IndexRangeScan", "FetchByRID", "Filter", "Project", "Result"]
    assert result.execution_plan["index_name"] == "b"
    assert result.execution_plan["steps"][1]["actual_rows"] == 7
    assert result.execution_plan["steps"][2]["actual_rows"] == 6
    engine.execute("CREATE INDEX h ON t(id) USING HASH;")
    plan = engine.execute("SELECT * FROM t WHERE id = 4;").execution_plan
    assert plan["index_name"] == "h" and operators(plan)[0] == "IndexScan"


def test_sequential_range_is_not_labeled_full_scan(tmp_path):
    engine = setup_table(tmp_path, "SEQUENTIAL")
    result = engine.execute("SELECT * FROM t WHERE id >= 7;")
    assert operators(result.execution_plan)[0] == "SequentialRangeScan"
    assert result.execution_plan["steps"][0]["actual_rows"] == 3
    assert operators(engine.explain("SELECT * FROM t WHERE price = 1;"))[0] == "FullScan"


def test_explain_delete_has_no_side_effects_or_fake_measurements(tmp_path):
    engine = setup_table(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    counters = engine.counter.snapshot()
    plan = engine.explain("DELETE FROM t WHERE id > 3;")
    assert plan["mode"] == "estimated" and plan["metrics"] is None
    assert all(s["actual_rows"] is None for s in plan["steps"])
    assert operators(plan) == ["FullScan", "Filter", "Delete"]
    assert engine.counter.snapshot() == counters
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = engine.execute("DELETE FROM t WHERE id > 3;")
    assert result.execution_plan["steps"][-1]["actual_rows"] == 6


@pytest.mark.parametrize("sql", ["SELECT missing FROM t;", "SELECT * FROM t WHERE missing = 1;", "DROP TABLE t;", "SELECT * FROM absent;"])
def test_explain_validates_without_mutations(tmp_path, sql):
    engine = setup_table(tmp_path)
    with pytest.raises(ValueError):
        engine.explain(sql)
    assert engine.execute("SELECT * FROM t;").total_rows == 10


def test_explain_api_and_query_plan(tmp_path):
    engine = setup_table(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/api/explain", json={"sql":"DELETE FROM t;"})
        assert response.status_code == 200
        assert response.json()["mode"] == "estimated"
        result = client.post("/api/query", json={"sql":"SELECT * FROM t;"}).json()
        assert result["total_rows"] == 10
        assert result["execution_plan"]["mode"] == "actual"
        assert client.post("/api/explain", json={"sql":"SELECT bad FROM t;"}).status_code == 400
