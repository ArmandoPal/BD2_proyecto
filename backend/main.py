"""Backend entry point.

Run with::

    uvicorn backend.main:app --reload --port 8000

Configuration comes from the environment so the benchmarks can point the API at
a different data directory or block size::

    BD2_DATA_DIR         directory holding the binary files (default data/processed)
    BD2_PAGE_SIZE        1024 | 2048 | 4096 | 8192      (default 4096)
    BD2_BUFFER_CAPACITY  frames in the buffer pool       (default 64)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import close_database, get_database, router


@asynccontextmanager
async def lifespan(app):
    """opens the database when the server starts and flushes it when the server stops."""
    get_database()
    yield
    close_database()


app = FastAPI(title="Gestor de Bases de Datos Multimodal - CS2042", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restringir en produccion
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def health_check():
    """liveness probe for the web client."""
    return {"status": "ok", "service": "gestor-bd-multimodal"}
