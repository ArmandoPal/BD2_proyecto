"""Query executor and its physical operators (enunciado 3.4).

Operators follow the iterator (Volcano) model: each one is a generator of
``<location, record>`` pairs pulled lazily by the one above it, which is the
"executes the plan node by node" stage of the architecture seen in class::

    Project  <-  Filter  <-  SeqScan | IndexScan | IndexRangeScan | BinarySearchScan

Every statement is wrapped in a DiskCounter measurement, so the result carries
the exact block reads and writes it caused, next to parse and execution time in
milliseconds.
"""

import time

from backend.catalog.schema_manager import CatalogError

from .parser import SQLParser, SQLSyntaxError
from .planner import AccessPath, QueryPlanner


class QueryResult:
    """what a statement returns: its rows plus the telemetry the metrics panel shows."""

    def __init__(self, rows=None, columns=None, disk_reads=0, disk_writes=0,
                 parse_time_ms=0.0, exec_time_ms=0.0, access_path=None, plan=None, message=""):
        """collects the rows and the measured cost of producing them."""
        self.rows = rows if rows is not None else []
        self.columns = columns or []
        self.disk_reads = disk_reads
        self.disk_writes = disk_writes
        self.parse_time_ms = parse_time_ms
        self.exec_time_ms = exec_time_ms
        self.access_path = access_path
        self.plan = plan
        self.message = message

    @property
    def row_count(self):
        """number of tuples returned, or affected for a write statement."""
        return len(self.rows)

    def to_dict(self):
        """json payload returned by POST /api/query."""
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "message": self.message,
            "access_path": self.access_path,
            "plan": self.plan,
            "metrics": {
                "disk_reads": self.disk_reads,
                "disk_writes": self.disk_writes,
                "parse_time_ms": round(self.parse_time_ms, 4),
                "exec_time_ms": round(self.exec_time_ms, 4),
                "total_time_ms": round(self.parse_time_ms + self.exec_time_ms, 4),
            },
        }

    def __repr__(self):
        return (f"QueryResult(rows={self.row_count}, path={self.access_path}, "
                f"reads={self.disk_reads}, writes={self.disk_writes})")


# ---------- physical operators ----------

def seq_scan(handle):
    """full table scan: pulls every record page by page, costing P block reads."""
    yield from handle.scan()


def index_scan(index, handle, key):
    """point lookup: asks the index for the RIDs of a key, then fetches each record."""
    for rid in index.search(key):
        record = handle.get(rid)
        if record is not None:
            yield rid, record


def index_range_scan(index, handle, low, high):
    """range lookup: walks the B+ leaf chain, then fetches one record per matching RID."""
    for _, rid in index.range_search(low, high):
        record = handle.get(rid)
        if record is not None:
            yield rid, record


def binary_search_scan(handle, equal=None, low=None, high=None):
    """sequential-file lookup: binary search over the sorted main pages, plus the overflow chain."""
    if equal is not None:
        yield from handle.search(equal)
        return
    yield from handle.range_search(low if low is not None else float("-inf"),
                                   high if high is not None else float("inf"))


def apply_filter(source, schema, predicate):
    """evaluates the remaining WHERE terms on each tuple the access path produced."""
    if predicate.is_empty():
        yield from source
        return
    positions = [(schema.index_of(term.column), term) for term in predicate.terms]
    for location, record in source:
        values = schema.unpack(record)
        if all(term.matches(values[position]) for position, term in positions):
            yield location, record


def project(source, schema, columns):
    """turns packed records into the dicts the API returns, keeping only the asked columns."""
    names = columns or schema.names
    positions = [schema.index_of(name) for name in names]
    for _, record in source:
        values = schema.unpack(record)
        yield {name: values[position] for name, position in zip(names, positions)}


# ---------- executor ----------

class QueryExecutor:
    """parses a statement, asks the planner for a route and runs the matching operator tree."""

    def __init__(self, database):
        """binds the executor to a database and builds its parser and planner."""
        self.database = database
        self.parser = SQLParser()
        self.planner = QueryPlanner(database.catalog, database)

    def execute(self, sql):
        """runs one statement end to end and returns its rows plus measured I/O and timings."""
        statement = self.parser.parse(sql)
        parse_time_ms = self.parser.parse_time_ms

        handlers = {
            "CREATE_TABLE": self._create_table,
            "DROP_TABLE": self._drop_table,
            "CREATE_INDEX": self._create_index,
            "DROP_INDEX": self._drop_index,
            "INSERT": self._insert,
            "SELECT": self._select,
            "DELETE": self._delete,
            "REORGANIZE": self._reorganize,
        }
        started = time.perf_counter()
        with self.database.counter.measure() as io:
            result = handlers[statement.kind](statement)
        result.exec_time_ms = (time.perf_counter() - started) * 1000
        result.parse_time_ms = parse_time_ms
        result.disk_reads = io["disk_reads"]
        result.disk_writes = io["disk_writes"]
        return result

    # ---------- DDL ----------

    def _create_table(self, statement):
        """creates the table and reports which storage engine backs it."""
        table = self.database.create_table(statement.table, statement.columns, statement.organization)
        return QueryResult(message=f"table {table.name!r} created USING {table.organization}")

    def _drop_table(self, statement):
        """drops a table and every file behind it."""
        self.database.drop_table(statement.table)
        return QueryResult(message=f"table {statement.table!r} dropped")

    def _create_index(self, statement):
        """builds an index and bulk-loads it from the records already stored."""
        index = self.database.create_index(statement.name, statement.table,
                                           statement.column, statement.index_kind)
        return QueryResult(message=f"index {index.name!r} created on {statement.table}({index.column}) "
                                   f"USING {index.kind}")

    def _drop_index(self, statement):
        """removes an index and its file."""
        self.database.drop_index(statement.table, statement.name)
        return QueryResult(message=f"index {statement.name!r} dropped")

    def _reorganize(self, statement):
        """rebuilds a sequential file and reports how it ended up laid out."""
        stats = self.database.reorganize(statement.table)
        return QueryResult(message=(f"table {statement.table!r} reorganized into {stats['pages']} pages "
                                    f"at {int(stats['fill_factor'] * 100)}% fill factor"))

    # ---------- DML ----------

    def _insert(self, statement):
        """inserts one or more tuples, reordering values when an explicit column list is given."""
        table = self.database.catalog.get_table(statement.table)
        schema = table.schema
        for values in statement.rows:
            self.database.insert(table.name, self._ordered_values(schema, statement.columns, values))
        return QueryResult(message=f"{len(statement.rows)} row(s) inserted into {table.name!r}")

    def _ordered_values(self, schema, columns, values):
        """maps an explicit column list back onto the table's declaration order."""
        if columns is None:
            return values
        if len(columns) != len(values):
            raise SQLSyntaxError(f"{len(columns)} columns but {len(values)} values")
        supplied = {name.lower(): value for name, value in zip(columns, values)}
        missing = [c.name for c in schema.columns if c.name.lower() not in supplied]
        if missing:
            raise SQLSyntaxError(f"missing value for column(s): {', '.join(missing)}")
        return [supplied[c.name.lower()] for c in schema.columns]

    def _select(self, statement):
        """plans the query, runs the operator tree and returns the projected rows."""
        table = self.database.catalog.get_table(statement.table)
        schema = table.schema
        plan = self.planner.plan(table.name, statement.predicate)
        source, residual = self._open_path(table, plan, statement.predicate)
        rows = list(project(apply_filter(source, schema, residual), schema, statement.columns))
        return QueryResult(rows=rows, columns=statement.columns or schema.names,
                           access_path=plan.access_path.value, plan=plan.to_dict())

    def _delete(self, statement):
        """finds the matching tuples through the planned path, then deletes them and their index keys."""
        table = self.database.catalog.get_table(statement.table)
        schema = table.schema
        plan = self.planner.plan(table.name, statement.predicate)
        source, residual = self._open_path(table, plan, statement.predicate)
        targets = list(apply_filter(source, schema, residual))
        removed = self.database.delete_rids(table.name, targets)
        return QueryResult(access_path=plan.access_path.value, plan=plan.to_dict(),
                           message=f"{removed} row(s) deleted from {table.name!r}")

    def _open_path(self, table, plan, predicate):
        """instantiates the operator the planner chose and returns the WHERE terms it did not consume."""
        handle = self.database.table_handle(table.name)

        if plan.access_path is AccessPath.SEQ_SCAN:
            return seq_scan(handle), predicate

        residual = self._residual(predicate, plan)

        if plan.access_path is AccessPath.INDEX_SCAN:
            index = self.database.index_handle(table.name, plan.index)
            return index_scan(index, handle, plan.equal), residual

        if plan.access_path is AccessPath.INDEX_RANGE_SCAN:
            index = self.database.index_handle(table.name, plan.index)
            return index_range_scan(index, handle, plan.low, plan.high), residual

        return binary_search_scan(handle, plan.equal, plan.low, plan.high), residual

    def _residual(self, predicate, plan):
        """drops the terms the access path already enforced, so Filter only checks what is left."""
        from .parser import Predicate
        strict = {"<", ">", "!="}
        remaining = []
        for term in predicate.terms:
            covered = (plan.column is not None
                       and term.column.lower() == plan.column.lower()
                       and term.operator not in strict)
            if not covered:
                remaining.append(term)
        return Predicate(remaining)


class QueryEngineError(Exception):
    """wraps parser and catalog failures so the API can answer 400 instead of 500."""


def run(database, sql):
    """one-shot helper: executes a statement and normalizes errors into QueryEngineError."""
    try:
        return QueryExecutor(database).execute(sql)
    except (SQLSyntaxError, CatalogError, KeyError, ValueError) as error:
        raise QueryEngineError(str(error)) from error
