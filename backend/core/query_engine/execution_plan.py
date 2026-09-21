"""Descripción del plan elegido, sin inventar costos ni tiempos por operador."""

from dataclasses import asdict
from .planner import AccessPath


def describe_plan(query, table, plan, counts=None):
    actual = counts is not None
    steps = []

    def add(operator, detail, rows=None):
        steps.append({"operator": operator, "detail": detail, "actual_rows": rows})

    scanned = counts["examined"] if actual else None
    matched = counts["matched"] if actual else None
    bounded = table.organization == "SEQUENTIAL" and any(
        c.column == table.primary_key and c.operator in ("=", ">", ">=", "<", "<=")
        for c in query.conditions
    )
    if plan.index:
        reason = (
            "Igualdad sobre una columna indexada; se prefiere Hash si está disponible."
            if plan.access_path == AccessPath.INDEX_SCAN
            else "El índice B+ permite recorrer las claves del rango solicitado."
        )
        add(plan.access_path.value, f"{plan.index.name} · {plan.index.kind} · {plan.index.column}")
        add("FetchByRID", f"Recuperar registros de {table.name} por página y slot", scanned)
    elif bounded:
        reason = "Sin índice público aplicable; se aprovecha el orden de la PRIMARY KEY."
        add("SequentialRangeScan", f"{table.name} · búsqueda acotada por {table.primary_key}", scanned)
    else:
        reason = "Sin índice público aplicable a los predicados; se recorre la tabla completa."
        add("FullScan", f"{table.name} · organización {table.organization}", scanned)
    if query.conditions:
        def literal(value):
            return "'" + value.replace("'", "''") + "'" if isinstance(value, str) else str(value)
        predicate = " AND ".join(
            f"{c.column} {c.operator} {literal(c.value)}" for c in query.conditions
        )
        add("Filter", predicate, matched)
    if query.kind == "DELETE":
        add("Delete", "Eliminar registros y actualizar todos los índices", counts["affected"] if actual else None)
    else:
        add("Project", ", ".join(query.projection), matched)
        add("Result", "Devolver la página solicitada; el total incluye todas las coincidencias", counts["returned"] if actual else None)
    return {
        "mode": "actual" if actual else "estimated",
        "statement": query.kind,
        "table": table.name,
        "organization": table.organization,
        "access_path": plan.access_path.value,
        "index_name": plan.index.name if plan.index else None,
        "reason": reason,
        "conditions": [asdict(c) for c in query.conditions],
        "steps": steps,
    }


def operation_plan(statement, table, operator, message, affected=None):
    return {
        "mode": "actual", "statement": statement, "table": table,
        "access_path": operator, "index_name": None,
        "reason": message,
        "steps": [{"operator": operator, "detail": message, "actual_rows": affected}],
    }
