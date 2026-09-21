"""Rutas HTTP del cliente SQL; las operaciones se serializan con un lock local."""

import tempfile
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Query
from starlette.concurrency import run_in_threadpool
from backend.core.catalog.csv_importer import import_csv
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=100000)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=1000)


class ReorganizeRequest(BaseModel):
    table_name: str


def run_operation(request, operation):
    with request.app.state.engine_lock:
        try:
            return operation(request.app.state.engine)
        except (ValueError, KeyError, UnicodeError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(
                status_code=500, detail=f"Error de archivo: {error}"
            ) from error


@router.post("/query")
def run_query(body: QueryRequest, request: Request):
    return run_operation(
        request,
        lambda engine: engine.execute(body.sql, body.offset, body.limit).to_dict(),
    )


@router.get("/tables")
def list_tables(request: Request):
    return run_operation(request, lambda engine: {"tables": engine.list_tables()})


@router.post("/tables/reorganize")
def reorganize_table(body: ReorganizeRequest, request: Request):
    return run_operation(
        request, lambda engine: engine.reorganize(body.table_name).to_dict()
    )


@router.post("/explain")
def explain_query(body: QueryRequest, request: Request):
    return run_operation(request, lambda engine: engine.explain(body.sql, body.offset, body.limit))


MAX_CSV_BYTES = 256 * 1024 * 1024


@router.post("/tables/import-csv")
async def import_csv_file(
    request: Request,
    table_name: str = Query(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$"),
    limit: int | None = Query(default=None, ge=1),
    organization: Literal["HEAP", "SEQUENTIAL"] = "HEAP",
    delimiter: Literal["auto", "comma", "semicolon", "tab"] = "auto",
):
    # Cuerpo CSV por bloques: no materializar el archivo completo en RAM.
    size = 0
    with tempfile.TemporaryFile() as upload:
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_CSV_BYTES:
                raise HTTPException(status_code=413, detail="El CSV supera el máximo de 256 MB")
            await run_in_threadpool(upload.write, chunk)
        return await run_in_threadpool(
            run_operation, request,
            lambda engine: import_csv(engine, upload, table_name, limit, organization, delimiter),
        )
