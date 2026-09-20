"""Rutas HTTP del cliente SQL; las operaciones se serializan con un lock local."""

from fastapi import APIRouter, HTTPException, Request
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
