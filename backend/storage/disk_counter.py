"""
DiskCounter (3.1 Capa de Almacenamiento Física)

Monitor obligatorio de I/O físico. Debe registrar exactamente:
    - disk_reads: bloques físicos leídos
    - disk_writes: bloques físicos escritos

Usado por el planificador/executor para reportar el desglose exacto de I/O
en cada consulta (ver 3.4).
"""


class DiskCounter:
    def __init__(self):
        self.disk_reads = 0
        self.disk_writes = 0

    def register_read(self):
        self.disk_reads += 1

    def register_write(self):
        self.disk_writes += 1

    def reset(self):
        self.disk_reads = 0
        self.disk_writes = 0

    def snapshot(self) -> dict:
        return {"disk_reads": self.disk_reads, "disk_writes": self.disk_writes}
