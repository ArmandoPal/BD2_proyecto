import io

import pytest
from fastapi.testclient import TestClient

from backend.api import routes
from backend.core.catalog.csv_importer import import_csv
from backend.core.catalog.table_storage import TableStorage
from backend.core.query_engine.executor import QueryExecutor
from backend.main import create_app


@pytest.mark.parametrize("organization", ["HEAP", "SEQUENTIAL"])
def test_csv_types_headers_limit_and_reopen(tmp_path, organization):
    engine = QueryExecutor(directory=tmp_path)
    content = ("Código;Nombre del artículo;Precio;Stock;Opcional\n"
               "001;Café;3.50;4;\n002;Té;2;0;ok\n003;No importar;9;1;x\n")
    result = import_csv(engine, io.BytesIO(content.encode("utf-8-sig")), "Catalogo", 2, organization)
    assert result["table"] == "catalogo" and result["affected_rows"] == 2
    assert result["delimiter"] == ";" and result["primary_key"] == "_row_id"
    assert [c["dtype"] for c in result["schema"]] == ["INT", "CHAR(3)", "CHAR(5)", "FLOAT", "INT", "CHAR(2)"]
    assert result["disk_writes"] > 0
    assert result["column_mapping"][1] == {"source": "Nombre del artículo", "column": "nombre_del_articulo"}
    reopened = QueryExecutor(directory=tmp_path)
    assert reopened.execute("SELECT * FROM catalogo;").rows == [
        {"_row_id": 1, "codigo": "001", "nombre_del_articulo": "Café", "precio": 3.5, "stock": 4, "opcional": ""},
        {"_row_id": 2, "codigo": "002", "nombre_del_articulo": "Té", "precio": 2.0, "stock": 0, "opcional": "ok"},
    ]
    assert not list(tmp_path.glob(".csv-import-*"))


def test_csv_full_inference_quoted_fields_and_generated_key(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    content = 'ID,Texto,Mixto\n001,"Lima, Perú",1\n001,"dos\nlíneas",texto largo\n'
    result = import_csv(engine, io.BytesIO(content.encode()), "t", limit=100)
    assert result["affected_rows"] == 2
    rows = engine.execute("SELECT * FROM t;").rows
    assert [r["id"] for r in rows] == ["001", "001"]
    assert rows[1]["texto"] == "dos\nlíneas"
    assert rows[0]["mixto"] == "1"
    assert rows[1]["mixto"] == "texto largo"


def test_limit_stops_before_invalid_row_and_blank_lines_do_not_count(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    result = import_csv(engine, io.BytesIO(b"a,b\n\n1,2\n3,4\ninvalid\n"), "t", limit=2, delimiter="comma")
    assert result["affected_rows"] == 2


@pytest.mark.parametrize("data", [
    b"", b"id,name\n", b"id,\n1,x\n", b"a-b,a b\n1,2\n",
    b"a,b\n1\n", b'a,b\n1,"unterminated', b"name\nx\x00y\n", b"name\n\xff\n",
    b"name\n" + b"x" * 5000 + b"\n",
])
def test_invalid_csv_does_not_publish_table_or_files(tmp_path, data):
    engine = QueryExecutor(directory=tmp_path)
    with pytest.raises(ValueError):
        import_csv(engine, io.BytesIO(data), "bad")
    assert engine.list_tables() == []
    assert list(tmp_path.iterdir()) == []


def test_existing_table_and_orphan_files_are_preserved(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    import_csv(engine, io.BytesIO(b"value\n1\n"), "t")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError, match="existente"):
        import_csv(engine, io.BytesIO(b"value\n2\n"), "t")
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    orphan = tmp_path / "other.__pk.idx"
    orphan.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="Existen archivos"):
        import_csv(engine, io.BytesIO(b"value\n3\n"), "other")
    assert orphan.read_bytes() == b"preserve"
    assert "other" not in engine.schema_manager.tables
    assert not (tmp_path / "other.bin").exists()


def test_insert_failure_cleans_staging_without_touching_catalog(tmp_path, monkeypatch):
    engine = QueryExecutor(directory=tmp_path)
    import_csv(engine, io.BytesIO(b"a\n1\n"), "existing")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    original = TableStorage.insert
    def fail_second(self, values):
        if values[0] == 2:
            raise OSError("simulated disk failure")
        return original(self, values)
    monkeypatch.setattr(TableStorage, "insert", fail_second)
    with pytest.raises(OSError):
        import_csv(engine, io.BytesIO(b"a\n1\n2\n"), "failed")
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert [t["name"] for t in engine.list_tables()] == ["existing"]


def test_integer_precision_and_empty_fields_are_preserved(tmp_path):
    engine = QueryExecutor(directory=tmp_path)
    content = b"large,mixed,empty,nonfinite\n9007199254740993,9007199254740993,,NaN\n9007199254740994,1.5,2,inf\n"
    import_csv(engine, io.BytesIO(content), "t")
    rows = engine.execute("SELECT * FROM t;").rows
    assert rows[0]["large"] == 9007199254740993
    assert rows[0]["mixed"] == "9007199254740993"
    assert rows[0]["empty"] == ""
    assert rows[0]["nonfinite"] == "NaN"


def test_csv_api_and_validation(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path)) as client:
        url = "/api/tables/import-csv"
        data = b"id\tname\n1\tAda\n2\tGrace\n"
        result = client.post(url, params={"table_name":"people", "delimiter":"tab", "limit":1}, content=data)
        assert result.status_code == 200 and result.json()["affected_rows"] == 1
        assert client.get("/api/tables").json()["tables"][0]["name"] == "people"
        assert client.post(url, params={"table_name":"people"}, content=data).status_code == 400
        for params in (
            {"table_name":"../invalid"}, {"table_name":"new", "limit":0},
            {"table_name":"new", "limit":-1}, {"table_name":"new", "limit":"abc"},
            {"table_name":"new", "organization":"OTHER"},
        ):
            assert client.post(url, params=params, content=data).status_code == 422
        monkeypatch.setattr(routes, "MAX_CSV_BYTES", 4)
        assert client.post(url, params={"table_name":"too_large"}, content=data).status_code == 413
        assert [t["name"] for t in client.get("/api/tables").json()["tables"]] == ["people"]
