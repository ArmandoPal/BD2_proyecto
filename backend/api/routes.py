"""REST API over the engine (enunciado 3.5).

Endpoints required by the enunciado::

    POST /api/query              run a statement, return tuples + I/O and timings
    GET  /api/tables             list tables with their organization and indexes
    POST /api/tables/reorganize  rebuild a sequential file's main area

Plus a couple the web client needs: a health probe and per-table detail.

The database lives for the whole process, so file handles and the buffer pool
are reused across requests instead of being reopened per query.
"""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.catalog.schema_manager import CatalogError
from backend.query_engine import Database, QueryExecutor
from backend.query_engine.parser import SQLSyntaxError

router = APIRouter(prefix="/api")

DATA_DIR = os.environ.get("BD2_DATA_DIR", "data/processed")
PAGE_SIZE = int(os.environ.get("BD2_PAGE_SIZE", "4096"))
BUFFER_CAPACITY = int(os.environ.get("BD2_BUFFER_CAPACITY", "64"))

_database = None
_executor = None


def get_database():
    """opens the process-wide database on first use so handles survive across requests."""
    global _database, _executor
    if _database is None:
        _database = Database(DATA_DIR, page_size=PAGE_SIZE, buffer_capacity=BUFFER_CAPACITY)
        _executor = QueryExecutor(_database)
    return _database


def get_executor():
    """returns the executor bound to the process-wide database."""
    get_database()
    return _executor


def close_database():
    """flushes and closes the database, called on application shutdown."""
    global _database, _executor
    if _database is not None:
        _database.close()
        _database = _executor = None


class QueryRequest(BaseModel):
    sql: str


class ReorganizeRequest(BaseModel):
    table_name: str


@router.post("/query")
def run_query(request: QueryRequest):
    """runs one SQL statement and returns its rows together with disk_reads, disk_writes and timings."""
    try:
        return get_executor().execute(request.sql).to_dict()
    except (SQLSyntaxError, CatalogError, ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/tables")
def list_tables():
    """lists every table with its columns, storage engine, active indexes and page count."""
    database = get_database()
    return {"tables": [database.table_info(table) for table in database.catalog.list_tables()]}


@router.get("/tables/{name}")
def describe_table(name: str):
    """returns the detail of one table, used by the table explorer panel."""
    database = get_database()
    try:
        return database.table_info(database.catalog.get_table(name))
    except CatalogError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/tables/reorganize")
def reorganize_table(request: ReorganizeRequest):
    """merges a sequential file's main and overflow areas and reports the resulting layout."""
    database = get_database()
    try:
        with database.counter.measure() as io:
            stats = database.reorganize(request.table_name)
        return {"table": request.table_name, "stats": stats, "metrics": io}
    except CatalogError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/health")
def health():
    """reports that the engine is up and which storage configuration it is running with."""
    database = get_database()
    return {
        "status": "ok",
        "data_dir": DATA_DIR,
        "page_size": database.page_size,
        "buffer_capacity": database.buffer_capacity,
        "tables": len(database.catalog.tables),
        "io": database.counter.snapshot(),
    }
