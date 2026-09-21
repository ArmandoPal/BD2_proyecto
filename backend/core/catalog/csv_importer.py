"""Importación de CSV en dos pasadas, con memoria acotada y publicación al finalizar."""

import csv
import io
import math
import re
import tempfile
import time
import unicodedata
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from .schema_manager import ColumnDef, identifier
from .table_storage import TableStorage
from backend.core.query_engine.executor import QueryExecutor, QueryResult
from backend.core.query_engine.execution_plan import operation_plan
from backend.core.storage.page import Page
from backend.core.storage.record_serializer import RecordSerializer

INTEGER = re.compile(r"[+-]?(?:0|[1-9][0-9]*)\Z")
DECIMAL = re.compile(r"[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t"}


def column_name(value):
    if not value.strip():
        raise ValueError("El CSV contiene un encabezado vacío")
    value = unicodedata.normalize("NFKD", value.strip()).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not value:
        raise ValueError("Un encabezado no se puede convertir en identificador SQL")
    if value[0].isdigit():
        value = "col_" + value
    return identifier(value)


def value_kind(value):
    if INTEGER.fullmatch(value):
        number = int(value)
        return "INT" if -(2**63) <= number < 2**63 else "TEXT"
    if DECIMAL.fullmatch(value) and math.isfinite(float(value)):
        return "FLOAT"
    return "TEXT"


def rows(reader, width, limit):
    # Las líneas completamente vacías no cuentan como registros.
    nonempty = (row for row in reader if row)
    for number, row in enumerate(islice(nonempty, limit), 1):
        if len(row) != width:
            raise ValueError(f"CSV línea {reader.line_num}: se esperaban {width} columnas y llegaron {len(row)}")
        if any("\0" in value for value in row):
            raise ValueError(f"CSV línea {reader.line_num}: texto con NUL no admitido")
        yield number, row


def inspect_csv(stream, delimiter, limit):
    sample = stream.read(8192)
    stream.seek(0)
    if delimiter == "auto":
        try:
            separator = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            separator = ","
    else:
        separator = DELIMITERS[delimiter]
    reader = csv.reader(stream, delimiter=separator, strict=True)
    header = next(reader, None)
    if not header:
        raise ValueError("El CSV está vacío o no tiene encabezados")
    names = [column_name(name) for name in header]
    if len(set(names)) != len(names):
        raise ValueError("Los encabezados se repiten después de normalizar sus nombres")
    kinds = [set() for _ in names]
    sizes = [1 for _ in names]
    large_int = [False for _ in names]
    count = 0
    for count, row in rows(reader, len(names), limit):
        for i, value in enumerate(row):
            kind = value_kind(value)
            kinds[i].add(kind)
            sizes[i] = max(sizes[i], len(value.encode("utf-8")))
            if kind == "INT" and abs(int(value)) > 2**53:
                large_int[i] = True
    if count == 0:
        raise ValueError("El CSV debe contener al menos una fila de datos")
    primary = "_row_id"
    while primary in names:
        primary = "_" + primary
    columns = [ColumnDef(primary, "INT", True)]
    for i, name in enumerate(names):
        if kinds[i] == {"INT"}:
            dtype = "INT"
        elif "TEXT" not in kinds[i] and not large_int[i]:
            dtype = "FLOAT"
        else:
            dtype = f"CHAR({sizes[i]})"
        columns.append(ColumnDef(name, dtype))
    return separator, header, columns, count


def import_csv(engine, binary, table_name, limit=None, organization="HEAP", delimiter="auto"):
    table_name = identifier(table_name)
    if table_name in engine.schema_manager.tables:
        raise ValueError(f"Tabla existente: {table_name}")
    if organization not in ("HEAP", "SEQUENTIAL"):
        raise ValueError("Organización no soportada")
    if delimiter not in ("auto", *DELIMITERS):
        raise ValueError("Separador no soportado")
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError("El límite debe ser un entero positivo")
    started = time.perf_counter()
    binary.seek(0)
    stream = io.TextIOWrapper(binary, encoding="utf-8-sig", newline="")
    try:
        separator, header, columns, count = inspect_csv(stream, delimiter, limit)
        size = RecordSerializer(columns).record_size
        # Sequential reserva la frontera y el enlace; el overflow añade un RID.
        Page(1, size, engine.page_size, bytes(16) if organization == "SEQUENTIAL" else b"")
        if organization == "SEQUENTIAL":
            Page(1, size + 8, engine.page_size)
        definitions = ", ".join(
            f"{c.name} {c.dtype}" + (" PRIMARY KEY" if c.primary_key else "")
            for c in columns
        )
        catalog = engine.schema_manager
        # La tabla solo se publica tras importar todas las filas seleccionadas.
        with tempfile.TemporaryDirectory(prefix=".csv-import-", dir=catalog.directory) as directory:
            staging = QueryExecutor(directory=directory, page_size=engine.page_size)
            staging.execute(f"CREATE TABLE {table_name} ({definitions}) USING {organization};")
            table = staging.schema_manager.get_table(table_name)
            stream.seek(0)
            reader = csv.reader(stream, delimiter=separator, strict=True)
            next(reader)
            with TableStorage(staging.schema_manager, table, staging.counter) as storage:
                for number, row in rows(reader, len(header), limit):
                    values = [number] + [
                        int(value) if c.dtype == "INT" else float(value) if c.dtype == "FLOAT" else value
                        for c, value in zip(columns[1:], row)
                    ]
                    storage.insert(values)
            files = [p for p in Path(directory).iterdir() if p.name != "catalog.json"]
            destinations = [catalog.directory / p.name for p in files]
            if any(p.exists() for p in destinations):
                raise ValueError("Existen archivos con ese nombre; elige otro nombre de tabla")
            moved = []
            try:
                for source, destination in zip(files, destinations):
                    source.replace(destination)
                    moved.append(destination)
                catalog.create_table(table)
            except Exception:
                if catalog.tables.get(table_name) is table:
                    del catalog.tables[table_name]
                for destination in moved:
                    destination.unlink(missing_ok=True)
                raise
            result = QueryResult(
                affected_rows=count, access_path="ImportCSV",
                disk_reads=staging.counter.disk_reads, disk_writes=staging.counter.disk_writes,
                exec_time_ms=(time.perf_counter() - started) * 1000,
                message=f"{count} filas importadas en {table_name}",
            )
        result.execution_plan = operation_plan("IMPORT", table_name, "ImportCSV", result.message, count)
        result.execution_plan["metrics"] = {
            "disk_reads": result.disk_reads, "disk_writes": result.disk_writes,
            "parse_time_ms": 0, "exec_time_ms": result.exec_time_ms,
        }
        return {
            **result.to_dict(), "table": table_name,
            "schema": [asdict(c) for c in columns],
            "column_mapping": [{"source": name, "column": c.name} for name, c in zip(header, columns[1:])],
            "primary_key": columns[0].name, "delimiter": separator,
        }
    except UnicodeError as error:
        raise ValueError("El CSV debe estar codificado en UTF-8 (con o sin BOM)") from error
    except csv.Error as error:
        raise ValueError(f"CSV inválido: {error}") from error
    finally:
        stream.detach()
