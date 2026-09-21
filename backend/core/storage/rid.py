"""Dirección lógica estable dentro de un archivo de datos."""

from typing import NamedTuple


class RID(NamedTuple):
    page_id: int
    slot_number: int
