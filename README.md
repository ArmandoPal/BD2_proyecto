# Atlas · Motor relacional en disco

Entregable 1 de Base de Datos II (CS2042). El repositorio original se completó con páginas binarias, Heap, Sequential, B+ multinivel, Extendible Hashing, SQL, FastAPI y un cliente web. Las tablas y los índices se implementan con `seek`, `read`, `write` y `struct`.

## Ejecutar el proyecto

Con las dependencias instaladas y el entorno virtual activo, inicia el proyecto desde la raíz:

```powershell
python run.py
```

Para preparar el entorno por primera vez:

Requiere Python 3.10 o posterior; el entorno verificado usa Python 3.12.14. `requirements-lock.txt` registra las versiones exactas de esa validación. Ejecuta los comandos desde la raíz del repositorio. No se necesita Node para usar el sistema.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe data/create_demo.py
.venv\Scripts\python.exe run.py
```

Abre **http://127.0.0.1:8000**. El mismo servidor entrega el frontend y la API; no abras `frontend/index.html` directamente. La documentación HTTP está en **http://127.0.0.1:8000/docs**. Detén el servidor con Ctrl+C.

En Linux/macOS usa `.venv/bin/python` en lugar de `.venv\Scripts\python.exe`. Con un entorno activo, todos los ejemplos se reducen a `python ...`.

En esta copia local ya se instaló y verificó `.venv`, y `data/database/` contiene `products` con 500000 filas y `products_demo`. Se puede iniciar directamente con `.venv\Scripts\python.exe run.py`. Para repetir la carga completa, indique una tabla o directorio nuevo, por ejemplo `--data-dir data/otra_carga`. El comando `python run.py --data-dir RUTA --port 8001` permite elegir otro directorio y puerto. Usa un solo proceso escritor: detén el backend antes de importar al mismo directorio.

## Dataset real: products-500000.csv

Se inspeccionó el archivo proporcionado: **500 000 filas**, 90 764 217 bytes, claves `Index` únicas y ascendentes de 1 a 500 000. `Index` se convierte en `product_id`; `Added Date` en `added_date` y `Internal ID` en `internal_id`. No se presume una fuente externa distinta del archivo recibido.

El importador busca el CSV en `data/raw/`, la raíz del proyecto y la carpeta Descargas del usuario. También admite una ruta explícita:

```powershell
.venv\Scripts\python.exe data/load_products.py --csv "C:\Users\USER\Downloads\products-500000.csv" --limit 500000
```

Cargas parciales independientes, con nombres distintos para no sobrescribir tablas:

```powershell
.venv\Scripts\python.exe data/load_products.py --limit 1000 --table products_1000
.venv\Scripts\python.exe data/load_products.py --limit 10000 --table products_10000
.venv\Scripts\python.exe data/load_products.py --limit 100000 --table products_100000
```

Para Sequential e índices públicos:

```powershell
.venv\Scripts\python.exe data/load_products.py --limit 10000 --table products_seq --organization SEQUENTIAL --indexes BTREE HASH
```

Opciones: `--data-dir`, `--table`, `--organization HEAP|SEQUENTIAL`, `--page-size 1024|2048|4096|8192`, `--indexes BTREE HASH`. Una tabla ya existente produce un error y se conserva. Si una importación falla, sus filas previas permanecen; usa otra tabla o directorio para repetirla.

La carga usa **CSV → RecordSerializer → TableStorage → Heap/Sequential → Page → DiskManager**, manteniendo también los índices. No precalcula un archivo binario externo ni carga el CSV completo en memoria. Cada tabla tiene un Hash privado para validar la PRIMARY KEY; su costo está incluido en las métricas de importación. El informe `TABLA.import.json` queda junto a sus archivos.

Esquema de 394 bytes por registro:

| Campo | Tipo | Campo | Tipo |
|---|---|---|---|
| product_id | INT | name | CHAR(80) |
| description | CHAR(100) | brand | CHAR(50) |
| category | CHAR(40) | price | FLOAT |
| currency | CHAR(3) | stock | INT |
| ean | CHAR(15) | color | CHAR(25) |
| size | CHAR(15) | availability | CHAR(15) |
| added_date | CHAR(15) | internal_id | CHAR(12) |

INT y FLOAT ocupan 8 bytes. CHAR(n) limita **bytes UTF-8**, no caracteres. EAN se conserva como texto, incluyendo ceros iniciales. Los valores demasiado largos se rechazan; no se truncan silenciosamente.

## SQL disponible

Una sentencia por solicitud; identificadores sin comillas e insensibles a mayúsculas, literales de texto con comillas simples. Se exige exactamente una PRIMARY KEY simple.

```sql
CREATE TABLE empleados (
    id INT PRIMARY KEY,
    nombre CHAR(30),
    dept CHAR(20),
    salario FLOAT
) USING HEAP;

INSERT INTO empleados VALUES (101, 'Ada Lovelace', 'Analytics', 5200.0);
SELECT * FROM empleados WHERE id = 101;
CREATE INDEX idx_emp_id ON empleados(id) USING BTREE;
SELECT nombre, salario FROM empleados WHERE id >= 100 AND id <= 500;
CREATE INDEX hash_emp_id ON empleados(id) USING HASH;
DELETE FROM empleados WHERE id = 101;
DELETE FROM empleados WHERE salario < 1000 AND dept = 'Analytics';
DELETE FROM empleados;
DROP TABLE empleados;
```

También se admite `USING SEQUENTIAL`, SELECT sin WHERE, proyección de columnas, operadores `=`, `<`, `>`, `<=`, `>=`, `!=`, `<>` y predicados combinados con AND. Una comilla literal se escribe `'O''Brien'`. No hay JOIN, UPDATE, OR, agregados, NULL ni SQL completo.

`DELETE FROM tabla WHERE ...` elimina todas las filas que cumplen el filtro y actualiza los índices, incluido el de PRIMARY KEY. `DELETE FROM tabla` vacía la tabla y conserva su esquema e índices; la paginación no limita los borrados. `DROP TABLE tabla` elimina del catálogo la tabla y borra sus archivos de datos, overflow e índices (incluidos los directorios Hash). Después se puede crear otra tabla con el mismo nombre. Una tabla inexistente produce un error. El menú «Ejemplos rápidos» incluye borrar una fila, vaciar y eliminar `products_demo`.

El planificador usa índices públicos: igualdad → `IndexScan`; rango con B+ → `IndexRangeScan`; resto → `SeqScan`. Si B+ y Hash aplican a igualdad, prefiere Hash. El índice privado de PRIMARY KEY no se utiliza para seleccionar filas. En Sequential, `SeqScan` puede usar búsqueda binaria y recorrido acotado del archivo ordenado.

## API y métricas

- `POST /api/query`: `{"sql":"SELECT * FROM products WHERE product_id = 500;", "offset":0, "limit":100}`.
- `GET /api/tables`: tablas, columnas, organización, tamaño de página e índices, incluidos los de integridad marcados como internos.
- `POST /api/tables/reorganize`: `{"table_name":"products_seq"}`. Reorganiza principal/overflow y reconstruye todos los índices.
- `GET /api/health`: disponibilidad del backend.

Las respuestas incluyen `rows`, `columns`, `total_rows`, `affected_rows`, `access_path`, `index_name`, `disk_reads`, `disk_writes`, `parse_time_ms` y `exec_time_ms`. La respuesta contiene como máximo 1000 filas. El total se cuenta recorriendo los candidatos; cambiar de página ejecuta de nuevo la consulta.

**Qué se cuenta:** llamadas completadas de lectura/escritura de páginas, incluidas páginas de metadata y asignaciones. El catálogo JSON, aperturas de archivos, `stat`, `rename` y `truncate` no se contabilizan como páginas. No son estimaciones ni mediciones de fallos de caché del SO. Python usa archivos sin buffering, pero el sistema operativo puede mantener caché. No se fuerza `fsync` por escritura.

El contador se reinicia por consulta. Las búsquedas por RID usan un buffer local de hasta 32 páginas de datos, vacío al empezar; las transferencias evitadas no suman lecturas. En benchmarks de igualdad el índice y la recuperación del producto se miden juntos.

## Estructura del código

```text
backend/
├── core/                          Implementación real del gestor
│   ├── storage/                   Almacenamiento físico
│   │   ├── page.py                Cabecera, bitmap, slots y Page Layout
│   │   ├── rid.py                 RID (página, slot)
│   │   ├── disk_counter.py        Lecturas y escrituras realizadas
│   │   ├── disk_manager.py        Offset y seek/read/write de páginas
│   │   └── record_serializer.py   Serialización de tipos mediante struct
│   ├── file_org/                  Organización de archivos
│   │   ├── heap_file.py           Heap y Free-List persistente
│   │   ├── sequential_file.py     Principal ordenado y reorganización
│   │   └── overflow_manager.py    Registros enlazados por RID
│   ├── indexes/                   Índices sobre archivos paginados
│   │   ├── bplus_node.py          Nodos internos/hoja y formato binario
│   │   ├── bplus_tree.py          Descenso, splits y hojas enlazadas
│   │   ├── hash_bucket.py         Bucket y serialización
│   │   ├── hash_directory.py      Directorio paginado
│   │   └── extendible_hash.py     Hashing, doubling y split
│   ├── catalog/                   Esquemas y coordinación tabla/índices
│   │   ├── schema_manager.py      Metadata de tablas e índices
│   │   └── table_storage.py       Apertura, PRIMARY KEY y mantenimiento
│   └── query_engine/              Parser, Planner y Executor
│       ├── tokenizer.py           Tokens del subconjunto SQL
│       ├── query_models.py        ParsedQuery y predicados
│       ├── parser.py              Gramática y validación sintáctica
│       ├── planner.py             choose_access_path()
│       └── executor.py            SQL, rutas y métricas
├── api/routes.py                  API REST
├── main.py                        FastAPI y frontend estático
└── tests/                         Pruebas funcionales y de persistencia
frontend/
├── index.html                 Cuatro áreas del cliente
└── src/
    ├── styles.css             Diseño y adaptación de tamaño
    ├── app.js                 Interacción, resultados y métricas
    └── services/api.js        Solicitudes reales a FastAPI
data/
├── products.py                Esquema y lectura streaming del CSV
├── load_products.py           Importador del motor
├── create_demo.py             Datos pequeños de demostración
└── generate_dataset.py        Recorte opcional del CSV original
benchmarks/
├── common.py                  Fixtures físicos y exportación
├── exp1_insercion_masiva.py
├── exp2_busqueda_puntual.py
├── exp3_busqueda_rango.py
├── exp4_sensibilidad_bloque.py
├── run_all.py                 Ejecución secuencial
├── results/                   CSV y evidencia real
└── plots/                     Gráficas de resultados
informe/                       Fuentes LaTeX e informe PDF
tools/                         Inspector, validación y compilación del informe
run.py                         Inicio de todo el sistema
EXPOSICION.md                  Mapa rápido de archivos y funciones
```

El flujo de la aplicación es **Frontend → API REST → `backend/core` → archivos binarios**. `backend/main.py` conecta FastAPI con `QueryExecutor`; el núcleo usa la biblioteca estándar y sus propios módulos, sin depender de FastAPI ni del frontend. El catálogo pertenece al núcleo porque define los esquemas y coordina las escrituras de tablas e índices. `data/` conserva los datasets e importadores y `benchmarks/` ejecuta los experimentos usando este mismo núcleo.

Las cinco carpetas que antes estaban directamente bajo `backend/` se trasladaron a `backend/core/`, incluidos sus auxiliares. Los imports usan `backend.core.storage`, `backend.core.file_org`, `backend.core.indexes`, `backend.core.catalog` y `backend.core.query_engine`; las rutas anteriores ya no existen. El formato de los archivos binarios, los endpoints y `python run.py` se mantienen.

## Pruebas y validaciones

```powershell
.venv\Scripts\python.exe -m pytest backend/tests -q
```

La última ejecución aprobó **63 pruebas, con 0 fallos**. La suite verifica Page Layout, RID, contador, offset, tipos, Heap/Free-List, Sequential/overflow/reorganización, B+ multinivel y rangos, Hash/doubling, persistencia, SQL, planner, executor y API, incluidos DELETE masivos con mantenimiento de índices y DROP TABLE con recreación. Las pruebas usan archivos temporales.

La reorganización a `backend/core/` se verificó con las mismas 41 pruebas antes y después, los cuatro experimentos con 1000 productos y una prueba HTTP/navegador en un proceso nuevo. Esas comprobaciones se guardan en `output/qa/core-refactor/` (excluido de Git); no sustituyen los CSV ni las gráficas históricos. También se compararon la lógica Python y los hashes de los datos/evidencias existentes.

La validación adicional `tools/validate_large_indexes.py` construye B+ y Hash sobre la carga de 500000 filas, los reabre y verifica todas las entradas B+ y 1002 búsquedas por índice.

Para repetir las cuatro importaciones con comparación de cada registro después de reabrir, usa un directorio nuevo:

```powershell
.venv\Scripts\python.exe tools/validate_products.py --data-dir data/validation_nueva
```

`benchmarks/results/import_validation.json` registra las cuatro cargas verificadas (1000, 10000, 100000 y 500000). La carga de 500000 tardó 323.0 s en este equipo; incluye comprobación de PRIMARY KEY. Los tiempos dependen de hardware y caché.

Inspector de archivos reales:

```powershell
.venv\Scripts\python.exe tools/inspect_page.py data/database/products.bin --page 0
.venv\Scripts\python.exe tools/inspect_page.py data/database/products.bin --page 1
```

La página cero muestra metadata; la página uno muestra cabecera, slots y offsets reales. Para otros tamaños usa `--page-size 1024` (o el tamaño del archivo).

## Cuatro benchmarks completos

```powershell
.venv\Scripts\python.exe -m benchmarks.run_all
```

También se ejecutan por separado:

```powershell
.venv\Scripts\python.exe benchmarks/exp1_insercion_masiva.py
.venv\Scripts\python.exe benchmarks/exp2_busqueda_puntual.py
.venv\Scripts\python.exe benchmarks/exp3_busqueda_rango.py
.venv\Scripts\python.exe benchmarks/exp4_sensibilidad_bloque.py
```

Todos aceptan `--csv RUTA`. El experimento 1 usa N = 1000, 10000, 50000, 100000, 250000, 500000. B+ y Hash incluyen un Heap de registros completos más el índice; las otras variantes son tablas sin índice. El CSV ascendente favorece el Sequential y casi no genera overflow; el costo de reorganizar incluye reescribir a fill factor 0.75. Las pruebas con inserciones desordenadas sí fuerzan y verifican overflow.

El experimento 2 usa N=100000 y 1000 consultas con semilla 42, devolviendo media y desviación estándar poblacional. El 3 usa selectividades 0.1%, 1%, 5%, 10% y 25%. Ambos cuentan la recuperación de registros y reutilizan un fixture físico, cuya carga queda fuera de la consulta medida. El 4 reconstruye un B+ con páginas de 1024, 2048, 4096 y 8192; aísla el índice y usa RID como etiquetas de prueba.

Prueba corta opcional:

```powershell
.venv\Scripts\python.exe benchmarks/exp1_insercion_masiva.py --sizes 1000
.venv\Scripts\python.exe benchmarks/exp2_busqueda_puntual.py --n 1000 --queries 20
```

**Estos comandos cortos sobrescriben los CSV/gráficas del mismo experimento.** Para conservar la evidencia completa, cópiala antes o vuelve a ejecutar los tamaños completos. Los fixtures quedan en `benchmarks/work/`, los datos tabulados en `benchmarks/results/` y las gráficas en `benchmarks/plots/`. Datos grandes y fixtures no se versionan; resultados y gráficas sí.

## Informe y exposición

Abre [EXPOSICION.md](EXPOSICION.md) durante la sustentación: contiene el orden de los 11 archivos principales, las funciones exactas y una demostración breve. `informe/main.tex` integra la descripción física y las cuatro comparaciones; `tools/build_report.py` genera las tablas desde los CSV reales y compila el PDF.

```powershell
.venv\Scripts\python.exe tools/build_report.py
```

Necesita [Tectonic](https://tectonic-typesetting.github.io/book/latest/installation/) o `pdflatex`. En este equipo se dispone del binario portátil oficial de Tectonic en `.tools/tectonic/`. Esa carpeta no se versiona; en otro equipo instala el compilador o usa `--compiler RUTA`. La primera compilación puede descargar paquetes LaTeX.

## Límites conocidos

- Un solo proceso escritor. El lock del backend no coordina procesos independientes.
- Sin WAL, transacciones, rollback ni recuperación automática ante interrupción entre varias escrituras. La reorganización completa de tabla e índices no es atómica ante fallos.
- El B+ elimina pares sin merge; el Hash no contrae su directorio ni recupera todas las páginas de colisión retiradas. Reconstruir índices recupera espacio.
- Hash limita la profundidad global a 20 y encadena colisiones/claves repetidas. Las listas largas degradan el rendimiento.
- Sequential se reorganiza explícitamente; el redondeo de slots puede producir una ocupación inferior al 75%, especialmente con páginas pequeñas.
- El catálogo administra metadata en JSON; las tablas, árboles, buckets y directorios siempre usan páginas binarias.
- El informe usa «Equipo del proyecto» porque no se proporcionaron integrantes. La grabación del video de exposición corresponde al equipo; se entrega el guion, no una grabación atribuida a personas.

No se incluyen componentes del Entregable 2.
