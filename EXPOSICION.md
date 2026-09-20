# Mapa rápido para la exposición · Entregable 1

Iniciar con `python run.py` (entorno virtual activo). Abrir http://127.0.0.1:8000 y ejecutar **una sentencia por vez**. Los archivos siguientes son los que utiliza el sistema.

## Recorrido recomendado

| Orden y archivo | Funciones que conviene abrir | Qué demuestra / concepto del curso | Operación para mostrarlo |
|---|---|---|---|
| 1. [storage/page.py](backend/core/storage/page.py) | `PageHeader.pack/unpack`, `Page.records_offset`, `Page.insert_record`, `Page.pack/unpack` | Page Layout: cabecera, bitmap, slots de tamaño fijo y serialización con `struct`. | Inspeccionar la página 1 con el comando de abajo; señalar slot, offset y registro. |
| 2. [storage/disk_manager.py](backend/core/storage/disk_manager.py) | `DiskManager.read_page`, `write_page`, `allocate_page` | `page_id × page_size → seek(offset) → read/write → archivo binario`. | Leer la página 1: offset 4096; insertar en la demo A y seguir las escrituras. |
| 3. [storage/disk_counter.py](backend/core/storage/disk_counter.py) | `DiskCounter.register_read`, `register_write`, `reset`, `snapshot` | I/O contado por transferencia de página completada. | Comparar las métricas de INSERT y SELECT en la demo A. |
| 4. [file_org/heap_file.py](backend/core/file_org/heap_file.py) | `HeapFile.insert`, `search`, `delete` | Heap, RID y Free-List persistente (`free_head`): reutilizar espacio sin recorrer toda la tabla. | Demo A; para reutilización de una página previamente llena, abrir `test_heap_freelist_persistence_and_reuse`. |
| 5. [file_org/sequential_file.py](backend/core/file_org/sequential_file.py) | `SequentialFile._find_page`, `insert`, `range_search`, `reorganize` | Búsqueda binaria sobre el principal ordenado; overflow; merge con fill factor 0.75. | Demo B: insertar 10, 20, 15; consultar y reorganizar. El redondeo de slots puede dejar menos del 75%. |
| 6. [file_org/overflow_manager.py](backend/core/file_org/overflow_manager.py) | `OverflowManager.insert`, `walk`, `delete`; constante `LINK` | Lista ordenada persistente enlazada por RID; cabeza guardada en la página principal. | Seguir el 15 de la demo B hasta el overflow y su integración al reorganizar. |
| 7. [indexes/bplus_tree.py](backend/core/indexes/bplus_tree.py) | `BPlusTree._find_leaf`, `search`, `range_search`, `_split_leaf`, `_insert_into_parent`, `_split_internal` | Key→RID, hojas enlazadas, split, propagación y nueva raíz en `_insert_into_parent`. | Demo A: igualdad y rango con B+. Para splits multinivel, abrir `test_bplus_multilevel_random_duplicates_range_reopen`. |
| 8. [indexes/extendible_hash.py](backend/core/indexes/extendible_hash.py) | `ExtendibleHash._hash`, `_bucket_index`, `insert`, `_split_bucket`, `_double_directory`, `iter_search` | Hash estable, bucket, local/global depth, redistribución y duplicación del directorio en disco. | Demo A: igualdad con Hash. Para doubling, abrir `test_hash_splits_directory_reopen_and_delete`. |
| 9. [query_engine/parser.py](backend/core/query_engine/parser.py) | `SQLParser.parse`, `_create` | SQL→tokens→`ParsedQuery`; gramática propia de CREATE TABLE/INDEX, INSERT, SELECT y DELETE. | Ejecutar CREATE, INSERT y SELECT de la demo A; mostrar el objeto interpretado. |
| 10. [query_engine/planner.py](backend/core/query_engine/planner.py) | `QueryPlanner.choose_access_path` | Igualdad+Hash/B+→`IndexScan`; rango+B+→`IndexRangeScan`; sin índice aplicable→`SeqScan`. | Repetir SELECT antes y después de crear índices en la demo A; Hash tiene prioridad en igualdad. |
| 11. [query_engine/executor.py](backend/core/query_engine/executor.py) | `QueryExecutor.execute`, `_candidates`, `reorganize`; `QueryResult.to_dict` | Coordinar interpretación, plan, estructura física, filtros, registros y métricas. | Seguir un SELECT desde la API hasta sus filas, `disk_reads`, `disk_writes`, `parse_time_ms` y `exec_time_ms`. |

## Archivos auxiliares que conviene tener a mano

Todas estas rutas están dentro de `backend/core/`:

- [storage/rid.py](backend/core/storage/rid.py): `RID(page_id, slot_number)`; [storage/record_serializer.py](backend/core/storage/record_serializer.py): `RecordSerializer.pack/unpack`, `field_value` y `KeyCodec` convierten tipos/bytes.
- [indexes/bplus_node.py](backend/core/indexes/bplus_node.py): `BPlusNode` y `NodeSerializer.pack/unpack`, claves, hijos y `next_leaf_id`/`prev_leaf_id`. [indexes/hash_bucket.py](backend/core/indexes/hash_bucket.py): `HashBucket.pack/unpack` y profundidad local. [indexes/hash_directory.py](backend/core/indexes/hash_directory.py): `HashDirectory.get`, `double`, `redirect` sobre páginas.
- [catalog/schema_manager.py](backend/core/catalog/schema_manager.py): `SchemaManager` guarda esquemas; [catalog/table_storage.py](backend/core/catalog/table_storage.py): `TableStorage.insert/delete`, `fetch_rids` mantienen índices y recuperan registros. El Hash privado valida PRIMARY KEY; el planner solo elige índices públicos.
- [query_engine/tokenizer.py](backend/core/query_engine/tokenizer.py): `tokenize`; [query_engine/query_models.py](backend/core/query_engine/query_models.py): `ParsedQuery`, `Condition`.

## Flujo real

```text
Frontend → API REST (backend/api) → backend/core
                                      │
                                     SQL
                                      ↓
                                    Parser
                                      ↓
                            ParsedQuery → Planner
                                      ↓
                             Access Path → Executor
                                      ↓
                         Heap / Sequential / B+ / Hash
                                      ↓
                              Page / DiskManager
                                      ↓
                              seek / read / write
                                      ↓
                                archivo binario
```

`QueryExecutor.execute` coordina el recorrido: llama al parser, usa el planner para SELECT/DELETE y ejecuta la ruta elegida. B+ y Hash devuelven RID; `TableStorage.fetch_rids` recupera el registro físico. Después devuelve filas y métricas a la API y al frontend. `data/` y `benchmarks/` también utilizan el núcleo, sin pasar por HTTP.

## Demo A · Heap, índices y decisión del planner

Usar nombres nuevos si estas tablas ya existen. Observar la ruta y los contadores en cada SELECT.

```sql
CREATE TABLE expo_heap (id INT PRIMARY KEY, nombre CHAR(30)) USING HEAP;
INSERT INTO expo_heap VALUES (10, 'Teclado');
INSERT INTO expo_heap VALUES (20, 'Monitor');
SELECT * FROM expo_heap WHERE id = 10;
CREATE INDEX expo_bplus ON expo_heap(id) USING BTREE;
SELECT * FROM expo_heap WHERE id = 10;
SELECT * FROM expo_heap WHERE id >= 10 AND id <= 20;
CREATE INDEX expo_hash ON expo_heap(id) USING HASH;
SELECT * FROM expo_heap WHERE id = 10;
DELETE FROM expo_heap WHERE id = 20;
INSERT INTO expo_heap VALUES (30, 'Mouse');
```

Las cuatro consultas muestran, en orden: `SeqScan`, `IndexScan` con B+, `IndexRangeScan` y `IndexScan` con Hash. La demo pequeña permite seguir el flujo; las pruebas de B+/Hash señaladas arriba fuerzan splits y crecimiento reales.

## Demo B · Overflow y reorganización

```sql
CREATE TABLE expo_seq (id INT PRIMARY KEY, nombre CHAR(30)) USING SEQUENTIAL;
INSERT INTO expo_seq VALUES (10, 'A');
INSERT INTO expo_seq VALUES (20, 'B');
INSERT INTO expo_seq VALUES (15, 'Overflow');
SELECT * FROM expo_seq WHERE id >= 10 AND id <= 20;
```

Abrir `expo_seq` en el explorador y pulsar **Reorganizar expo_seq**; repetir SELECT: 10, 15, 20. `QueryExecutor.reorganize` reconstruye también los índices porque cambian los RID. El overflow usa un Heap auxiliar; los RID públicos con página negativa distinguen esos registros del principal.

## Comprobación final

```powershell
python tools/inspect_page.py data/database/products.bin --page 1
python -m pytest backend/tests -q
rg -n "PARTE IMPORTANTE PARA EXPOSICION" backend/core
```

El inspector usa la carga local de `products` (si no está importada, elegir `expo_heap.bin`). La suite conserva 41 pruebas: páginas, Free-List, overflow, splits multinivel, doubling, persistencia, parser, planner, executor y API. Los cuatro benchmarks permanecen en `benchmarks/`; los resultados históricos se conservan.

Límites a declarar: un escritor, sin WAL/transacciones ni recuperación ante fallos de varias escrituras; B+ sin merge al borrar; Hash sin contracción; reorganización explícita; SQL acotado. La grabación y los integrantes de la portada quedan a cargo del equipo.
