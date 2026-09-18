"""
API REST (3.5 Backend API REST y Frontend Web)

Endpoints requeridos:
    POST /api/query               -> procesa consulta SQL, retorna tuplas + métricas I/O y tiempo
    GET  /api/tables               -> lista tablas y sus índices activos
    POST /api/tables/reorganize    -> dispara reorganize() sobre un Sequential File
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api")


class QueryRequest(BaseModel):
    sql: str


class ReorganizeRequest(BaseModel):
    table_name: str


@router.post("/query")
def run_query(request: QueryRequest):
    """TODO: usar QueryExecutor, retornar filas + disk_reads/writes + tiempos."""
    raise NotImplementedError


@router.get("/tables")
def list_tables():
    """TODO: retornar tablas del SchemaManager con sus índices activos."""
    raise NotImplementedError


@router.post("/tables/reorganize")
def reorganize_table(request: ReorganizeRequest):
    """TODO: invocar SequentialFile.reorganize() sobre la tabla indicada."""
    raise NotImplementedError
