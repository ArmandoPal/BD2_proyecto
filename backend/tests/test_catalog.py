"""Unit tests for record serialization and the persisted system catalog."""

import pytest

from backend.catalog import (
    CatalogError,
    Column,
    IndexDef,
    Schema,
    SchemaManager,
    TableDef,
    pack_rid,
    unpack_rid,
)
from backend.catalog.record import TypeError_, normalize_type, type_size


# ---------- record layout ----------

def test_types_are_normalized_before_the_layout_is_fixed():
    assert normalize_type("char( 30 )") == "CHAR(30)"
    assert normalize_type("int") == "INT"
    with pytest.raises(TypeError_):
        normalize_type("TEXT")


def test_every_supported_type_has_a_fixed_width():
    assert (type_size("INT"), type_size("FLOAT"), type_size("BOOL"), type_size("CHAR(30)")) == (4, 8, 1, 30)


def test_record_roundtrip_preserves_values_and_trims_char_padding():
    schema = Schema([Column("id", "INT"), Column("name", "CHAR(10)"), Column("price", "FLOAT")])
    raw = schema.pack([7, "ada", 12.5])
    assert len(raw) == schema.record_size == 22
    assert schema.unpack(raw) == [7, "ada", 12.5]


def test_oversized_char_values_are_truncated_not_rejected():
    schema = Schema([Column("name", "CHAR(4)")])
    assert schema.unpack(schema.pack(["lovelace"])) == ["love"]


def test_wrong_arity_is_rejected():
    schema = Schema([Column("id", "INT"), Column("name", "CHAR(4)")])
    with pytest.raises(ValueError):
        schema.pack([1])


def test_duplicate_column_names_are_rejected():
    with pytest.raises(ValueError):
        Schema([Column("id", "INT"), Column("ID", "INT")])


def test_rid_roundtrip():
    assert unpack_rid(pack_rid((70000, 12))) == (70000, 12)


def test_key_of_reads_one_column_out_of_a_packed_record():
    schema = Schema([Column("id", "INT"), Column("name", "CHAR(8)")])
    assert schema.key_of(schema.pack([42, "x"]), "ID") == 42


# ---------- catalog ----------

@pytest.fixture
def catalog(tmp_path):
    """fresh catalog rooted at a temporary data directory."""
    manager = SchemaManager(str(tmp_path / "data"))
    yield manager
    manager.close()


def employees():
    """table definition reused by the catalog tests."""
    return TableDef("empleados", [
        Column("id", "INT", primary_key=True),
        Column("nombre", "CHAR(30)"),
        Column("salario", "FLOAT"),
    ], "HEAP")


def test_created_table_is_readable_case_insensitively(catalog):
    catalog.create_table(employees())
    assert catalog.get_table("EMPLEADOS").primary_key == "id"
    assert catalog.has_table("Empleados")


def test_duplicate_table_is_rejected(catalog):
    catalog.create_table(employees())
    with pytest.raises(CatalogError):
        catalog.create_table(employees())


def test_unknown_table_raises_a_clear_error(catalog):
    with pytest.raises(CatalogError):
        catalog.get_table("ghost")


def test_bad_organization_is_rejected():
    with pytest.raises(CatalogError):
        TableDef("t", [Column("id", "INT")], "COLUMNAR")


def test_index_must_target_an_existing_column(catalog):
    catalog.create_table(employees())
    with pytest.raises(CatalogError):
        catalog.add_index("empleados", IndexDef("bad", "missing", "BTREE"))


def test_two_indexes_of_the_same_kind_on_one_column_are_rejected(catalog):
    catalog.create_table(employees())
    catalog.add_index("empleados", IndexDef("i1", "id", "BTREE"))
    with pytest.raises(CatalogError):
        catalog.add_index("empleados", IndexDef("i2", "id", "BTREE"))


def test_btree_and_hash_can_coexist_on_one_column(catalog):
    catalog.create_table(employees())
    catalog.add_index("empleados", IndexDef("i1", "id", "BTREE"))
    catalog.add_index("empleados", IndexDef("i2", "id", "HASH"))
    table = catalog.get_table("empleados")
    assert table.index_on("id", "HASH").name == "i2"


def test_catalog_survives_a_restart(tmp_path):
    path = str(tmp_path / "data")
    first = SchemaManager(path)
    first.create_table(employees())
    first.add_index("empleados", IndexDef("idx_emp_id", "id", "BTREE"))
    first.close()

    second = SchemaManager(path)
    table = second.get_table("empleados")
    assert [c.name for c in table.columns] == ["id", "nombre", "salario"]
    assert table.organization == "HEAP"
    assert table.index_on("id").kind == "BTREE"
    second.close()


def test_many_tables_spill_across_catalog_pages(tmp_path):
    path = str(tmp_path / "data")
    manager = SchemaManager(path, page_size=1024)
    for i in range(30):
        manager.create_table(TableDef(f"t{i}", [Column("id", "INT"), Column("payload", "CHAR(40)")]))
    manager.close()

    reopened = SchemaManager(path, page_size=1024)
    assert len(reopened.list_tables()) == 30
    assert reopened.disk.num_pages() > 1
    reopened.close()


def test_drop_table_removes_metadata_and_files(catalog):
    catalog.create_table(employees())
    catalog.drop_table("empleados")
    assert not catalog.has_table("empleados")
    with pytest.raises(CatalogError):
        catalog.drop_table("empleados")
