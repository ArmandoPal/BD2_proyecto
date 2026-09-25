"""INT de 64 bits, FLOAT de 64 bits y CHAR(n) de n bytes UTF-8."""

import math
import re
import struct


class RecordSerializer:
    def __init__(self, columns):
        self.columns = [
            (c.name, c.dtype) if hasattr(c, "name") else tuple(c) for c in columns
        ]
        self.fields = []
        self.record_size = 0
        for name, dtype in self.columns:
            dtype = dtype.upper()
            match = re.fullmatch(r"CHAR\(([1-9][0-9]*)\)", dtype)
            if dtype not in ("INT", "FLOAT") and not match:
                raise ValueError(f"Tipo no soportado: {dtype}")
            size = int(match[1]) if match else 8
            self.fields.append((name, dtype, self.record_size, size))
            self.record_size += size

    # PARTE IMPORTANTE PARA EXPOSICION: REGISTROS Y FORMATO BINARIO
    # Los tamaños fijos permiten recuperar cada campo por su offset.
    def pack(self, values):
        if isinstance(values, dict):
            values = [values[name] for name, _ in self.columns]
        if len(values) != len(self.fields):
            raise ValueError("Cantidad de valores incorrecta")
        parts = []
        for value, (name, dtype, _, size) in zip(values, self.fields):
            if dtype == "INT":
                if type(value) is not int or not -(2**63) <= value < 2**63:
                    raise ValueError(f"{name} requiere INT de 64 bits")
                parts.append(struct.pack("<q", value))
            elif dtype == "FLOAT":
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f"{name} requiere FLOAT finito")
                parts.append(struct.pack("<d", value))
            else:
                if not isinstance(value, str) or "\0" in value:
                    raise ValueError(f"{name} requiere texto sin NUL")
                raw = value.encode("utf-8")
                if len(raw) > size:
                    raise ValueError(f"{name} supera CHAR({size}) bytes UTF-8")
                parts.append(raw.ljust(size, b"\0"))
        return b"".join(parts)

    def unpack(self, data):
        if len(data) != self.record_size:
            raise ValueError("Registro truncado")
        return {
            name: self.field_value(data, i) for i, (name, _) in enumerate(self.columns)
        }

    def field_value(self, data, index):
        _, dtype, offset, size = self.fields[index]
        if dtype == "INT":
            return struct.unpack_from("<q", data, offset)[0]
        if dtype == "FLOAT":
            return struct.unpack_from("<d", data, offset)[0]
        return data[offset : offset + size].rstrip(b"\0").decode("utf-8")


class KeyCodec:
    """El mismo formato de una columna se usa en hojas y buckets."""

    def __init__(self, dtype="INT"):
        self.dtype = dtype
        self.serializer = RecordSerializer([("key", dtype)])
        self.size = self.serializer.record_size

    def pack(self, key):
        return self.serializer.pack([key])

    def unpack(self, data):
        return self.serializer.field_value(data, 0)
