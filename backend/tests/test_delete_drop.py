import pytest
from fastapi.testclient import TestClient

from backend.core.catalog.table_storage import TableStorage
from backend.core.query_engine.executor import QueryExecutor
from backend.main import create_app


def populate(engine, organization):
    engine.execute(
        f"CREATE TABLE t(id INT PRIMARY KEY, label CHAR(20)) USING {organization};"
    )
    # Inserciones descendentes concentran muchos registros en una cadena overflow.
    for key in [0, *range(119, 0, -1)]:
        engine.execute(f"INSERT INTO t VALUES ({key}, 'group{key % 2}');")
    engine.execute("CREATE INDEX by_id ON t(id) USING BTREE;")
    engine.execute("CREATE INDEX by_label_b ON t(label) USING BTREE;")
    engine.execute("CREATE INDEX by_label_h ON t(label) USING HASH;")


@pytest.mark.parametrize("organization", ["HEAP", "SEQUENTIAL"])
@pytest.mark.parametrize(
    "where,path,index,deleted",
    [
        ("", "SeqScan", None, set(range(120))),
        (" WHERE id != 0", "SeqScan", None, set(range(1, 120))),
        (
            " WHERE label = 'group1' AND id > 20",
            "IndexScan", "by_label_h", set(range(21, 120, 2)),
        ),
        (
            " WHERE id >= 20 AND id < 100",
            "IndexRangeScan", "by_id", set(range(20, 100)),
        ),
    ],
)
def test_delete_many_rows_preserves_indexes_and_restart(
    tmp_path, organization, where, path, index, deleted
):
    engine = QueryExecutor(directory=tmp_path, page_size=1024)
    populate(engine, organization)
    table = engine.schema_manager.get_table("t")
    files_before = {p.name for p in tmp_path.iterdir()}
    if organization == "SEQUENTIAL":
        with TableStorage(engine.schema_manager, table, engine.counter) as storage:
            assert storage.records.overflow.heap.count > 100

    # LIMIT y OFFSET solo paginan SELECT, nunca limitan una mutación.
    result = engine.execute("DELETE FROM t" + where + ";", offset=10, limit=1)
    assert result.affected_rows == len(deleted)
    assert result.rows == [] and result.columns == [] and result.total_rows == 0
    assert result.message == f"{len(deleted)} filas eliminadas"
    assert result.access_path == path and result.index_name == index
    assert result.disk_reads > 0 and result.disk_writes > 0
    assert {p.name for p in tmp_path.iterdir()} == files_before

    engine = QueryExecutor(directory=tmp_path)
    expected = set(range(120)) - deleted
    assert {r["id"] for r in engine.execute("SELECT * FROM t;").rows} == expected
    table = engine.schema_manager.get_table("t")
    with TableStorage(engine.schema_manager, table, engine.counter) as storage:
        assert storage.records.count == len(expected)
        for key in range(120):
            assert bool(storage.indexes["__pk_t"].search(key)) == (key in expected)
            assert bool(storage.indexes["by_id"].search(key)) == (key in expected)
        for label in ("group0", "group1"):
            expected_ids = {k for k in expected if f"group{k % 2}" == label}
            for name in ("by_label_b", "by_label_h"):
                rows = storage.fetch_rids(storage.indexes[name].search(label))
                assert {storage.serializer.unpack(raw)["id"] for _, raw in rows} == expected_ids

    assert engine.execute("DELETE FROM t WHERE id = 999;").affected_rows == 0
    key = min(deleted)
    engine.execute(f"INSERT INTO t VALUES ({key}, 'reinserted');")
    assert engine.execute(f"SELECT * FROM t WHERE id = {key};").rows == [
        {"id": key, "label": "reinserted"}
    ]


@pytest.mark.parametrize("organization", ["HEAP", "SEQUENTIAL"])
def test_drop_removes_only_owned_files_and_allows_recreation(tmp_path, organization):
    engine = QueryExecutor(directory=tmp_path, page_size=1024)
    populate(engine, organization)
    owned_files = {p for p in tmp_path.iterdir() if p.name != "catalog.json"}
    engine.execute("CREATE TABLE t_other(id INT PRIMARY KEY) USING HEAP;")
    engine.execute("INSERT INTO t_other VALUES (7);")
    unrelated = tmp_path / "t.notes.txt"
    unrelated.write_text("preserve", encoding="utf-8")
    preserved = {
        p: p.read_bytes() for p in tmp_path.iterdir()
        if p not in owned_files and p.name != "catalog.json"
    }

    result = engine.execute("DROP TABLE T;")
    assert result.access_path == "DropTable"
    assert result.message == "Tabla t eliminada"
    assert result.rows == [] and result.affected_rows == 0
    assert all(not p.exists() for p in owned_files)
    assert all(p.read_bytes() == data for p, data in preserved.items())
    assert [t["name"] for t in engine.list_tables()] == ["t_other"]
    # Unlink/catalog.json no son transferencias de páginas binarias.
    assert result.disk_reads == result.disk_writes == 0

    engine = QueryExecutor(directory=tmp_path)
    with pytest.raises(ValueError, match="Tabla inexistente"):
        engine.execute("SELECT * FROM t;")
    with pytest.raises(ValueError, match="Tabla inexistente"):
        engine.execute("DROP TABLE t;")
    assert engine.execute("SELECT * FROM t_other;").rows == [{"id": 7}]
    populate(engine, organization)
    assert engine.execute("SELECT * FROM t;").total_rows == 120


def test_delete_invalid_predicate_leaves_rows_unchanged(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    populate(engine, "HEAP")
    for query in (
        "DELETE FROM t WHERE missing = 1;",
        "DELETE FROM t WHERE id = 'invalid';",
        "DELETE FROM t WHERE id > 1 AND missing = 2;",
        "DROP TABLE t WHERE id = 1;",
    ):
        with pytest.raises(ValueError):
            engine.execute(query)
    assert engine.execute("SELECT * FROM t;").total_rows == 120


def test_drop_table_with_missing_file(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    engine.execute("CREATE TABLE t(id INT PRIMARY KEY) USING HEAP;")
    (tmp_path / "t.bin").unlink()
    engine.execute("DROP TABLE t;")
    assert engine.list_tables() == []
    assert {p.name for p in tmp_path.iterdir()} == {"catalog.json"}


def test_delete_and_drop_through_api(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        def sql(query):
            return client.post("/api/query", json={"sql": query})

        assert sql("CREATE TABLE t(id INT PRIMARY KEY) USING SEQUENTIAL;").status_code == 200
        sql("INSERT INTO t VALUES (1);")
        sql("INSERT INTO t VALUES (2);")
        result = sql("DELETE FROM t WHERE id = 1;")
        assert result.status_code == 200 and result.json()["affected_rows"] == 1
        assert sql("SELECT * FROM t;").json()["rows"] == [{"id": 2}]
        assert sql("DELETE FROM t;").json()["affected_rows"] == 1
        assert len(client.get("/api/tables").json()["tables"]) == 1
        result = sql("DROP TABLE t;")
        assert result.status_code == 200 and result.json()["access_path"] == "DropTable"
        assert client.get("/api/tables").json()["tables"] == []
        assert sql("DROP TABLE t;").status_code == 400
        assert sql("DELETE FROM t;").status_code == 400
        assert sql("CREATE TABLE t(id INT PRIMARY KEY) USING HEAP;").status_code == 200
