# Gestor de Bases de Datos Multimodal — CS2042 (2026-II)

Mini-Gestor de Bases de Datos Multimodal implementado desde cero sobre memoria
secundaria (disco), con estructuras de página/bloque binarias, punteros y
serialización de bajo nivel (`seek`, `read`, `write`, `struct`).

> Restricción arquitectural: no se usan motores de BD existentes (SQLite,
> PostgreSQL, MySQL, DuckDB, etc.) ni ORMs. Toda estructura física está
> codificada por el equipo.

## Integrantes

- Nombre 1 — código
- Nombre 2 — código
- Nombre 3 — código
- Nombre 4 — código

## Estructura del repositorio

```
backend/        Núcleo del motor (storage, file_org, indexes, query_engine, catalog, api)
frontend/       Cliente web (explorador de tablas, editor SQL, resultados, métricas)
data/           Datasets crudos y procesados para pruebas
benchmarks/     Scripts y resultados de los 4 experimentos de la Sección 4
informe/        Informe técnico en LaTeX
```

## Cómo levantar el sistema (1 solo paso)

### Requisitos previos
- Python 3.10+
- Node.js 18+ (solo si el frontend usa un bundler; si es HTML/JS plano, no aplica)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r ../requirements.txt
uvicorn main:app --reload --port 8000
```

La API queda disponible en `http://localhost:8000`.

### Frontend

```bash
cd frontend
# Si es HTML/JS plano, simplemente abrir index.html o servir con:
python -m http.server 5500
# Si usa Vite/React:
# npm install && npm run dev
```

### Preparar el dataset de prueba

```bash
cd data
python generate_dataset.py
```

Esto genera `data/processed/dataset.csv` con el volumen configurado
(100,000–500,000 registros).

### Correr los experimentos (Sección 4 del enunciado)

```bash
cd benchmarks
python exp1_insercion_masiva.py
python exp2_busqueda_puntual.py
python exp3_busqueda_rango.py
python exp4_sensibilidad_bloque.py
```

Los resultados crudos se guardan en `benchmarks/results/` y las gráficas en
`benchmarks/plots/`.

## Componentes del motor (Entregable 1)

| Módulo | Ubicación | Descripción |
|---|---|---|
| Almacenamiento paginado | `backend/storage/` | Page Layout, RID, DiskCounter |
| Heap File | `backend/file_org/heap_file.py` | Inserción O(1), free-list / move-the-last |
| Sequential File | `backend/file_org/sequential_file.py` | Área principal + overflow + reorganización |
| Árbol B+ | `backend/indexes/bplus_tree.py` | Búsqueda puntual y por rango en disco |
| Hashing Dinámico | `backend/indexes/extendible_hash.py` | Extendible o Linear Hashing |
| Parser SQL | `backend/query_engine/parser.py` | CREATE TABLE, INSERT, SELECT, DELETE, CREATE INDEX |
| Planificador | `backend/query_engine/planner.py` | SeqScan / IndexScan / IndexRangeScan |
| API REST | `backend/api/routes.py` | `/api/query`, `/api/tables`, `/api/tables/reorganize` |

## Dataset

- **Fuente:** (completar con el dataset elegido y su link)
- **Volumen usado:** (completar, mínimo 100,000 registros)
- **Esquema:** (completar tipos de columnas: INT, CHAR(n), FLOAT)

## Licencia / Uso académico

Proyecto desarrollado para el curso Base de Datos II (CS2042), UTEC, 2026-II.
Docente: Percy Lovon Ramos.
