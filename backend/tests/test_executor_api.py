import pytest
from fastapi.testclient import TestClient
from backend.core.query_engine.executor import QueryExecutor
from backend.main import create_app


@pytest.mark.parametrize("organization", ["HEAP", "SEQUENTIAL"])
def test_executor_paths_types_mutations_and_restart(tmp_path, organization):
    engine = QueryExecutor(directory=tmp_path, page_size=1024)
    engine.execute(
        f"CREATE TABLE t(id INT PRIMARY KEY, name CHAR(20), price FLOAT) USING {organization};"
    )
    for i in range(80):
        engine.execute(f"INSERT INTO t VALUES ({i}, 'name{i % 3}', {i}.5);")
    result = engine.execute("SELECT * FROM t WHERE id = 40;")
    assert result.access_path == "SeqScan" and result.total_rows == 1
    assert result.disk_reads > 0 and result.disk_writes == 0
    engine.execute("CREATE INDEX b ON t(id) USING BTREE;")
    result = engine.execute("SELECT * FROM t WHERE id > 30 AND id < 40;")
    assert result.access_path == "IndexRangeScan" and result.total_rows == 9
    engine.execute("CREATE INDEX h ON t(id) USING HASH;")
    assert engine.execute("SELECT * FROM t WHERE id = 40;").index_name == "h"
    engine.execute("CREATE INDEX names ON t(name) USING BTREE;")
    assert engine.execute("SELECT id FROM t WHERE name = 'name0';").total_rows == 27
    assert engine.execute("DELETE FROM t WHERE id = 40;").affected_rows == 1
    engine.execute("INSERT INTO t VALUES (40, 'changed', 9.5);")
    with pytest.raises(ValueError):
        engine.execute("INSERT INTO t VALUES (40, 'x', 1);")
    with pytest.raises(ValueError):
        engine.execute("INSERT INTO t VALUES ('oops', 'x', 1);")
    with pytest.raises(ValueError):
        engine.execute("SELECT * FROM t WHERE missing=1;")
    if organization == "SEQUENTIAL":
        engine.reorganize("t")
    engine = QueryExecutor(directory=tmp_path)
    assert engine.execute("SELECT * FROM t WHERE id = 40;").rows[0]["name"] == "changed"
    page = engine.execute("SELECT * FROM t;", offset=20, limit=15)
    assert page.total_rows == 80 and len(page.rows) == 15


def test_hash_not_used_for_ranges(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY) USING HEAP;")
    engine.execute("CREATE INDEX h ON t(id) USING HASH;")
    assert engine.execute("SELECT * FROM t WHERE id >= 10;").access_path == "SeqScan"


def test_api_real_engine_and_errors(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/health").json()["status"] == "ok"

        def sql(query):
            return client.post("/api/query", json={"sql": query})

        assert (
            sql("CREATE TABLE t(id INT PRIMARY KEY) USING SEQUENTIAL;").status_code
            == 200
        )
        assert sql("INSERT INTO t VALUES (12);").json()["disk_writes"] > 0
        assert sql("SELECT * FROM t WHERE id=12;").json()["rows"] == [{"id": 12}]
        assert client.get("/api/tables").json()["tables"][0]["name"] == "t"
        assert (
            client.post("/api/tables/reorganize", json={"table_name": "t"}).status_code
            == 200
        )
        assert sql("SELECT * FROM missing;").status_code == 400
        assert sql("INSERT INTO t VALUES (12);").status_code == 400
        assert (
            client.post(
                "/api/query", json={"sql": "SELECT * FROM t;", "limit": 10000}
            ).status_code
            == 422
        )


def test_missing_storage_is_not_silently_recreated(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE t (id INT PRIMARY KEY) USING HEAP;")
    (tmp_path / "t.__pk.idx").unlink()
    with pytest.raises(ValueError, match="ausente"):
        engine.execute("SELECT * FROM t;")
    assert not (tmp_path / "t.__pk.idx").exists()


import os
import subprocess
import sys


def test_reopen_in_new_process_with_different_hash_seed(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE t (id CHAR(10) PRIMARY KEY, value INT) USING HEAP;")
    engine.execute("INSERT INTO t VALUES ('Lima', 12);")
    engine.execute("CREATE INDEX h ON t(id) USING HASH;")
    code = "from backend.core.query_engine.executor import QueryExecutor; import sys; e=QueryExecutor(directory=sys.argv[1]); assert e.execute(\"SELECT * FROM t WHERE id='Lima';\").rows==[{'id':'Lima','value':12}]"
    subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "1234"},
    )
