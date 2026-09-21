"""Contador de transferencias completas; no estima costos ni fallos de caché del SO."""


class DiskCounter:
    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: I/O CONTADO, NO ESTIMADO
    # ============================================================
    def __init__(self):
        self.reset()

    def register_read(self):
        self.disk_reads += 1

    def register_write(self):
        self.disk_writes += 1

    def reset(self):
        self.disk_reads = 0
        self.disk_writes = 0

    def snapshot(self):
        return {"disk_reads": self.disk_reads, "disk_writes": self.disk_writes}
