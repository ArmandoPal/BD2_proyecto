"""
Ejecutor de Consultas (3.4 Motor de Consultas y Parser SQL)

Ejecuta el plan elegido por el planner y reporta el desglose exacto:
    - bloques leídos / escritos (vía DiskCounter)
    - tiempo de parseo (ms)
    - tiempo de ejecución (ms)
"""

import time


class QueryResult:
    def __init__(self, rows, disk_reads, disk_writes, parse_time_ms, exec_time_ms, access_path):
        self.rows = rows
        self.disk_reads = disk_reads
        self.disk_writes = disk_writes
        self.parse_time_ms = parse_time_ms
        self.exec_time_ms = exec_time_ms
        self.access_path = access_path


class QueryExecutor:
    def __init__(self, schema_manager, planner):
        self.schema_manager = schema_manager
        self.planner = planner

    def execute(self, sql: str) -> QueryResult:
        """TODO: parse -> plan -> ejecutar sobre HeapFile/SequentialFile/B+/Hash -> métricas."""
        raise NotImplementedError
