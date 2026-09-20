"""Access-path selection and analytic cost estimation (enunciado 3.4).

The rule the engine follows when it inspects a WHERE clause::

    equality  + HASH index      ->  IndexScan        ~1 bucket read + 1 fetch
    equality  + BTREE index     ->  IndexScan        ~h reads + 1 fetch
    range     + BTREE index     ->  IndexRangeScan   ~h + leaves + matched fetches
    predicate on the PK of a    ->  BinarySearchScan ~log2(M) reads
      sequential file
    anything else               ->  SeqScan          ~P reads

Estimated costs are in block reads and are reported next to the measured ones,
so the report can contrast the formula with what the DiskCounter actually saw.
An unclustered index costs one extra random read per matching tuple, which is
why a wide range can legitimately lose to a full scan -- the planner says so in
its `reason` field.
"""

import math
from enum import Enum


class AccessPath(Enum):
    SEQ_SCAN = "SeqScan"
    INDEX_SCAN = "IndexScan"
    INDEX_RANGE_SCAN = "IndexRangeScan"
    BINARY_SEARCH = "BinarySearchScan"


class Plan:
    """the chosen access path plus everything the executor and the metrics panel need."""

    __slots__ = ("access_path", "table", "column", "index", "equal", "low", "high",
                 "estimated_reads", "reason")

    def __init__(self, access_path, table, column=None, index=None,
                 equal=None, low=None, high=None, estimated_reads=0, reason=""):
        """records the decision and the numbers that justify it."""
        self.access_path = access_path
        self.table = table
        self.column = column
        self.index = index
        self.equal = equal
        self.low = low
        self.high = high
        self.estimated_reads = estimated_reads
        self.reason = reason

    def to_dict(self):
        """json view shown in the execution-plan panel of the web client."""
        return {
            "access_path": self.access_path.value,
            "table": self.table,
            "column": self.column,
            "index": self.index.name if self.index else None,
            "index_kind": self.index.kind if self.index else None,
            "equal": self.equal,
            "low": self.low,
            "high": self.high,
            "estimated_reads": self.estimated_reads,
            "reason": self.reason,
        }

    def __repr__(self):
        return f"Plan({self.access_path.value} on {self.table}, est_reads={self.estimated_reads})"


class QueryPlanner:
    """inspects the WHERE clause against the catalog and picks the cheapest available path."""

    def __init__(self, schema_manager, database=None):
        """keeps the catalog for metadata and the database for live page counts."""
        self.schema_manager = schema_manager
        self.database = database

    def plan(self, table_name, predicate):
        """returns the Plan for a predicate: index scan, binary search or full scan."""
        table = self.schema_manager.get_table(table_name)
        pages = self._data_pages(table_name)

        if predicate.is_empty():
            return Plan(AccessPath.SEQ_SCAN, table.name, estimated_reads=pages,
                        reason="no WHERE clause: every page must be read")

        for column in predicate.columns():
            equal, low, high = predicate.bounds_for(column)

            if equal is not None:
                hash_index = table.index_on(column, "HASH")
                if hash_index:
                    return Plan(AccessPath.INDEX_SCAN, table.name, column, hash_index, equal=equal,
                                estimated_reads=2,
                                reason="equality on a HASH index: one bucket read plus one record fetch")
                btree = table.index_on(column, "BTREE")
                if btree:
                    height = self._index_height(table.name, btree)
                    return Plan(AccessPath.INDEX_SCAN, table.name, column, btree, equal=equal,
                                estimated_reads=height + 1,
                                reason=f"equality on a BTREE index: h={height} reads plus one record fetch")

            if low is not None or high is not None:
                btree = table.index_on(column, "BTREE")
                if btree:
                    height = self._index_height(table.name, btree)
                    matches = self._estimate_matches(table_name, btree, low, high)
                    estimate = height + max(1, matches // 32) + matches
                    if estimate < pages:
                        return Plan(AccessPath.INDEX_RANGE_SCAN, table.name, column, btree,
                                    low=low, high=high, estimated_reads=estimate,
                                    reason=("range on a BTREE index: h reads, then the leaf chain, plus one "
                                            "random fetch per matching tuple because the index is unclustered"))
                    return Plan(AccessPath.SEQ_SCAN, table.name, estimated_reads=pages,
                                reason=(f"a BTREE index exists on {column}, but the range selects about "
                                        f"{matches} tuples: {estimate} random reads would cost more than "
                                        f"scanning all {pages} pages, so the full scan wins"))

            if table.organization == "SEQUENTIAL" and self._is_key_column(table, column):
                main_pages = self._main_pages(table_name) or pages
                estimate = max(1, math.ceil(math.log2(main_pages or 1))) + 1
                return Plan(AccessPath.BINARY_SEARCH, table.name, column, equal=equal, low=low, high=high,
                            estimated_reads=estimate,
                            reason=f"sequential file keyed by {column}: binary search over {main_pages} sorted pages")

        return Plan(AccessPath.SEQ_SCAN, table.name, estimated_reads=pages,
                    reason="no usable index on the predicate columns: full table scan")

    def choose_access_path(self, table_name, predicate):
        """convenience wrapper returning only the AccessPath, kept for callers that just need the label."""
        return self.plan(table_name, predicate).access_path

    # ---------- statistics ----------

    def _is_key_column(self, table, column):
        """true when a column is the sort key of the table's sequential file."""
        primary = table.primary_key
        return primary is not None and primary.lower() == column.lower()

    def _data_pages(self, table_name):
        """current number of data pages, read from the open file when the engine has one."""
        handle = self._handle(table_name)
        return handle.num_data_pages if handle else 1

    def _main_pages(self, table_name):
        """number of sorted main pages of a sequential file, 0 for other organizations."""
        handle = self._handle(table_name)
        return getattr(handle, "num_main_pages", 0) if handle else 0

    def _index_height(self, table_name, index_def):
        """height of a B+ tree, which is exactly what a point lookup costs in block reads."""
        if self.database is None:
            return 3
        try:
            return max(1, self.database.index_handle(table_name, index_def).height())
        except Exception:
            return 3

    def _estimate_matches(self, table_name, index_def, low, high):
        """estimates how many tuples a range returns, assuming keys are spread uniformly over the span."""
        handle = self._handle(table_name)
        records = handle.num_records if handle else 0
        if not records:
            return 1
        selectivity = self._selectivity(table_name, index_def, low, high)
        return max(1, int(records * selectivity))

    def _selectivity(self, table_name, index_def, low, high):
        """fraction of the key domain a range covers; falls back to 10% when the span is unknown."""
        default = 0.1
        if self.database is None:
            return default
        try:
            span = self.database.index_handle(table_name, index_def).key_span()
        except Exception:
            return default
        if not span:
            return default
        minimum, maximum = span
        if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)):
            return default
        width = maximum - minimum
        if width <= 0:
            return default
        lower = minimum if low is None else max(low, minimum)
        upper = maximum if high is None else min(high, maximum)
        return min(1.0, max(0.0, (upper - lower) / width)) or (1.0 / max(1, width))

    def _handle(self, table_name):
        """returns the open file of a table, or None when the planner has no database attached."""
        if self.database is None:
            return None
        try:
            return self.database.table_handle(table_name)
        except Exception:
            return None
