"""Esquema y lectura incremental del CSV products-500000.csv proporcionado."""

import csv
from pathlib import Path
from backend.core.catalog.schema_manager import ColumnDef
from backend.core.storage.record_serializer import RecordSerializer

FIELDS = [
    ("Index", "product_id", "INT"),
    ("Name", "name", "CHAR(80)"),
    ("Description", "description", "CHAR(100)"),
    ("Brand", "brand", "CHAR(50)"),
    ("Category", "category", "CHAR(40)"),
    ("Price", "price", "FLOAT"),
    ("Currency", "currency", "CHAR(3)"),
    ("Stock", "stock", "INT"),
    ("EAN", "ean", "CHAR(15)"),
    ("Color", "color", "CHAR(25)"),
    ("Size", "size", "CHAR(15)"),
    ("Availability", "availability", "CHAR(15)"),
    ("Added Date", "added_date", "CHAR(15)"),
    ("Internal ID", "internal_id", "CHAR(12)"),
]
COLUMNS = [ColumnDef(name, dtype, name == "product_id") for _, name, dtype in FIELDS]
SERIALIZER = RecordSerializer(COLUMNS)


def find_csv(value=None):
    if value:
        path = Path(value)
        if not path.is_file():
            raise ValueError(f"CSV inexistente: {path}")
        return path
    for path in (
        Path("data/raw/products-500000.csv"),
        Path("products-500000.csv"),
        Path.home() / "Downloads/products-500000.csv",
    ):
        if path.is_file():
            return path
    raise ValueError("No se encontró products-500000.csv; indique --csv RUTA")


def product_rows(path, limit=None):
    if limit is not None and limit < 1:
        raise ValueError("limit debe ser positivo")
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != [source for source, _, _ in FIELDS]:
            raise ValueError("Las columnas del CSV no coinciden con products")
        for number, row in enumerate(reader, 1):
            if limit is not None and number > limit:
                break
            try:
                values = [
                    int(row[source])
                    if dtype == "INT"
                    else float(row[source])
                    if dtype == "FLOAT"
                    else row[source]
                    for source, _, dtype in FIELDS
                ]
                SERIALIZER.pack(values)
            except (ValueError, TypeError) as error:
                raise ValueError(f"CSV fila {number + 1}: {error}") from error
            yield values


def create_sql(name, organization="HEAP"):
    columns = ", ".join(
        c.name + " " + c.dtype + (" PRIMARY KEY" if c.primary_key else "")
        for c in COLUMNS
    )
    return f"CREATE TABLE {name} ({columns}) USING {organization};"
