"""SQL lexer and recursive-descent parser (enunciado 3.4).

Hand written on purpose: no parsing dependency, and the tokenizer is the natural
place to measure ``parse_time_ms``.

Grammar accepted by the relational engine::

    CREATE TABLE t (col TYPE [PRIMARY KEY], ...) [USING HEAP|SEQUENTIAL];
    DROP TABLE t;
    INSERT INTO t [(cols)] VALUES (...) [, (...)];
    CREATE INDEX name ON t (col) [USING BTREE|HASH];
    DROP INDEX name ON t;
    SELECT * | cols FROM t [WHERE cond];
    DELETE FROM t [WHERE cond];
    REORGANIZE TABLE t;

    cond := term [AND term]*
    term := col (= | != | <> | < | <= | > | >=) value
          | col BETWEEN value AND value
"""

import re
import time

KEYWORDS = {
    "CREATE", "TABLE", "DROP", "INSERT", "INTO", "VALUES", "INDEX", "ON", "USING",
    "SELECT", "FROM", "WHERE", "DELETE", "AND", "BETWEEN", "PRIMARY", "KEY",
    "HEAP", "SEQUENTIAL", "BTREE", "HASH", "REORGANIZE", "INT", "FLOAT", "BOOL", "CHAR",
    "TRUE", "FALSE", "NOT", "NULL",
}

TOKEN_PATTERN = re.compile(r"""
    (?P<WS>\s+)
  | (?P<COMMENT>--[^\n]*)
  | (?P<NUMBER>-?\d+\.\d+|-?\d+)
  | (?P<STRING>'(?:[^']|'')*'|"(?:[^"]|"")*")
  | (?P<IDENT>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<OP><=|>=|<>|!=|=|<|>)
  | (?P<PUNCT>[(),;*.])
""", re.VERBOSE)

COMPARISONS = {"=", "!=", "<>", "<", "<=", ">", ">="}


class SQLSyntaxError(Exception):
    """raised when the token stream does not match the grammar."""


class Token:
    """one lexical unit: its kind, its text and where it started."""

    __slots__ = ("kind", "value", "position")

    def __init__(self, kind, value, position):
        """stores the token kind, its literal text and its offset in the statement."""
        self.kind = kind
        self.value = value
        self.position = position

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r})"


def tokenize(sql):
    """splits a statement into tokens, dropping whitespace and comments (lexer phase)."""
    tokens, position = [], 0
    while position < len(sql):
        match = TOKEN_PATTERN.match(sql, position)
        if match is None:
            raise SQLSyntaxError(f"unexpected character {sql[position]!r} at position {position}")
        kind = match.lastgroup
        text = match.group()
        position = match.end()
        if kind in ("WS", "COMMENT"):
            continue
        if kind == "IDENT" and text.upper() in KEYWORDS:
            kind = "KEYWORD"
            text = text.upper()
        tokens.append(Token(kind, text, match.start()))
    tokens.append(Token("EOF", "", len(sql)))
    return tokens


# ---------- AST ----------

class ParsedQuery:
    """base class of every parsed statement; carries the kind the planner switches on."""

    kind = "UNKNOWN"

    def __repr__(self):
        fields = ", ".join(f"{name}={getattr(self, name)!r}" for name in self.__slots__)
        return f"{type(self).__name__}({fields})"


class Comparison:
    """a single WHERE term: column, operator and the literal it is compared against."""

    __slots__ = ("column", "operator", "value")

    def __init__(self, column, operator, value):
        """normalizes '<>' into '!=' so the executor has one spelling to handle."""
        self.column = column
        self.operator = "!=" if operator == "<>" else operator
        self.value = value

    def matches(self, actual):
        """evaluates the term against a value already extracted from a record."""
        if self.operator == "=":
            return actual == self.value
        if self.operator == "!=":
            return actual != self.value
        if self.operator == "<":
            return actual < self.value
        if self.operator == "<=":
            return actual <= self.value
        if self.operator == ">":
            return actual > self.value
        return actual >= self.value

    def __repr__(self):
        return f"{self.column} {self.operator} {self.value!r}"


class Predicate:
    """a WHERE clause: a list of comparisons joined by AND."""

    __slots__ = ("terms",)

    def __init__(self, terms=None):
        """keeps the terms in written order; an empty predicate matches everything."""
        self.terms = list(terms or [])

    def columns(self):
        """set of column names the predicate touches, used by the planner."""
        return {term.column.lower() for term in self.terms}

    def bounds_for(self, column):
        """collapses the terms on one column into <equal, low, high>, the shape an index needs."""
        equal, low, high = None, None, None
        for term in self.terms:
            if term.column.lower() != column.lower():
                continue
            if term.operator == "=":
                equal = term.value
            elif term.operator == ">=":
                low = term.value if low is None else max(low, term.value)
            elif term.operator == ">":
                low = term.value if low is None else max(low, term.value)
            elif term.operator == "<=":
                high = term.value if high is None else min(high, term.value)
            elif term.operator == "<":
                high = term.value if high is None else min(high, term.value)
        return equal, low, high

    def is_empty(self):
        """true when there is no WHERE clause at all."""
        return not self.terms

    def __repr__(self):
        return " AND ".join(repr(term) for term in self.terms) or "TRUE"


class CreateTable(ParsedQuery):
    kind = "CREATE_TABLE"
    __slots__ = ("table", "columns", "organization")

    def __init__(self, table, columns, organization):
        self.table = table
        self.columns = columns          # list of (name, dtype, is_primary_key)
        self.organization = organization


class DropTable(ParsedQuery):
    kind = "DROP_TABLE"
    __slots__ = ("table",)

    def __init__(self, table):
        self.table = table


class Insert(ParsedQuery):
    kind = "INSERT"
    __slots__ = ("table", "columns", "rows")

    def __init__(self, table, columns, rows):
        self.table = table
        self.columns = columns          # None means "every column, in order"
        self.rows = rows


class CreateIndex(ParsedQuery):
    kind = "CREATE_INDEX"
    __slots__ = ("name", "table", "column", "index_kind")

    def __init__(self, name, table, column, index_kind):
        self.name = name
        self.table = table
        self.column = column
        self.index_kind = index_kind


class DropIndex(ParsedQuery):
    kind = "DROP_INDEX"
    __slots__ = ("name", "table")

    def __init__(self, name, table):
        self.name = name
        self.table = table


class Select(ParsedQuery):
    kind = "SELECT"
    __slots__ = ("table", "columns", "predicate")

    def __init__(self, table, columns, predicate):
        self.table = table
        self.columns = columns          # None means SELECT *
        self.predicate = predicate


class Delete(ParsedQuery):
    kind = "DELETE"
    __slots__ = ("table", "predicate")

    def __init__(self, table, predicate):
        self.table = table
        self.predicate = predicate


class Reorganize(ParsedQuery):
    kind = "REORGANIZE"
    __slots__ = ("table",)

    def __init__(self, table):
        self.table = table


# ---------- parser ----------

class SQLParser:
    """recursive-descent parser turning a statement into one ParsedQuery node."""

    def __init__(self):
        """starts with an empty token stream; parse() fills it per statement."""
        self.tokens = []
        self.position = 0
        self.parse_time_ms = 0.0

    # -- token helpers --

    def _peek(self):
        """returns the current token without consuming it."""
        return self.tokens[self.position]

    def _next(self):
        """consumes and returns the current token."""
        token = self.tokens[self.position]
        self.position += 1
        return token

    def _accept(self, kind, value=None):
        """consumes the current token when it matches, otherwise leaves the stream untouched."""
        token = self._peek()
        if token.kind == kind and (value is None or token.value.upper() == value):
            return self._next()
        return None

    def _expect(self, kind, value=None):
        """consumes the current token or fails with the position and what was expected."""
        token = self._accept(kind, value)
        if token is None:
            actual = self._peek()
            wanted = value or kind
            raise SQLSyntaxError(f"expected {wanted!r} at position {actual.position}, got {actual.value!r}")
        return token

    # -- entry point --

    def parse(self, sql):
        """tokenizes a statement, dispatches on its first keyword and times the whole phase."""
        started = time.perf_counter()
        self.tokens = tokenize(sql.strip())
        self.position = 0

        token = self._peek()
        if token.kind != "KEYWORD":
            raise SQLSyntaxError(f"statement must start with a keyword, got {token.value!r}")
        handlers = {
            "CREATE": self._parse_create,
            "DROP": self._parse_drop,
            "INSERT": self._parse_insert,
            "SELECT": self._parse_select,
            "DELETE": self._parse_delete,
            "REORGANIZE": self._parse_reorganize,
        }
        if token.value not in handlers:
            raise SQLSyntaxError(f"unsupported statement {token.value!r}")
        statement = handlers[token.value]()
        self._accept("PUNCT", ";")
        if self._peek().kind != "EOF":
            raise SQLSyntaxError(f"unexpected trailing input at position {self._peek().position}")
        self.parse_time_ms = (time.perf_counter() - started) * 1000
        return statement

    # -- statements --

    def _parse_create(self):
        """routes CREATE TABLE and CREATE INDEX to their own productions."""
        self._expect("KEYWORD", "CREATE")
        if self._accept("KEYWORD", "TABLE"):
            return self._parse_create_table()
        self._expect("KEYWORD", "INDEX")
        return self._parse_create_index()

    def _parse_create_table(self):
        """reads the column list and the optional USING clause that picks the file organization."""
        table = self._identifier()
        self._expect("PUNCT", "(")
        columns = [self._parse_column()]
        while self._accept("PUNCT", ","):
            columns.append(self._parse_column())
        self._expect("PUNCT", ")")

        organization = "HEAP"
        if self._accept("KEYWORD", "USING"):
            token = self._expect("KEYWORD")
            if token.value not in ("HEAP", "SEQUENTIAL"):
                raise SQLSyntaxError(f"unknown storage engine {token.value!r}")
            organization = token.value
        return CreateTable(table, columns, organization)

    def _parse_column(self):
        """parses one column definition: name, type and an optional PRIMARY KEY marker."""
        name = self._identifier()
        token = self._expect("KEYWORD")
        if token.value == "CHAR":
            self._expect("PUNCT", "(")
            width = int(self._expect("NUMBER").value)
            self._expect("PUNCT", ")")
            dtype = f"CHAR({width})"
        elif token.value in ("INT", "FLOAT", "BOOL"):
            dtype = token.value
        else:
            raise SQLSyntaxError(f"unknown column type {token.value!r}")

        primary = False
        if self._accept("KEYWORD", "PRIMARY"):
            self._expect("KEYWORD", "KEY")
            primary = True
        return (name, dtype, primary)

    def _parse_create_index(self):
        """reads the index name, its table and column, and the USING clause that picks the structure."""
        name = self._identifier()
        self._expect("KEYWORD", "ON")
        table = self._identifier()
        self._expect("PUNCT", "(")
        column = self._identifier()
        self._expect("PUNCT", ")")

        kind = "BTREE"
        if self._accept("KEYWORD", "USING"):
            token = self._expect("KEYWORD")
            if token.value not in ("BTREE", "HASH"):
                raise SQLSyntaxError(f"unknown index type {token.value!r}")
            kind = token.value
        return CreateIndex(name, table, column, kind)

    def _parse_drop(self):
        """parses DROP TABLE and DROP INDEX."""
        self._expect("KEYWORD", "DROP")
        if self._accept("KEYWORD", "TABLE"):
            return DropTable(self._identifier())
        self._expect("KEYWORD", "INDEX")
        name = self._identifier()
        self._expect("KEYWORD", "ON")
        return DropIndex(name, self._identifier())

    def _parse_insert(self):
        """parses INSERT INTO with an optional column list and one or more VALUES tuples."""
        self._expect("KEYWORD", "INSERT")
        self._expect("KEYWORD", "INTO")
        table = self._identifier()

        columns = None
        if self._accept("PUNCT", "("):
            columns = [self._identifier()]
            while self._accept("PUNCT", ","):
                columns.append(self._identifier())
            self._expect("PUNCT", ")")

        self._expect("KEYWORD", "VALUES")
        rows = [self._value_tuple()]
        while self._accept("PUNCT", ","):
            rows.append(self._value_tuple())
        return Insert(table, columns, rows)

    def _value_tuple(self):
        """parses one parenthesized list of literals."""
        self._expect("PUNCT", "(")
        values = [self._literal()]
        while self._accept("PUNCT", ","):
            values.append(self._literal())
        self._expect("PUNCT", ")")
        return values

    def _parse_select(self):
        """parses the projection list, the source table and the optional WHERE clause."""
        self._expect("KEYWORD", "SELECT")
        if self._accept("PUNCT", "*"):
            columns = None
        else:
            columns = [self._identifier()]
            while self._accept("PUNCT", ","):
                columns.append(self._identifier())
        self._expect("KEYWORD", "FROM")
        table = self._identifier()
        return Select(table, columns, self._parse_where())

    def _parse_delete(self):
        """parses DELETE FROM with its optional WHERE clause."""
        self._expect("KEYWORD", "DELETE")
        self._expect("KEYWORD", "FROM")
        table = self._identifier()
        return Delete(table, self._parse_where())

    def _parse_reorganize(self):
        """parses the maintenance statement that rebuilds a sequential file."""
        self._expect("KEYWORD", "REORGANIZE")
        self._accept("KEYWORD", "TABLE")
        return Reorganize(self._identifier())

    def _parse_where(self):
        """parses a WHERE clause into a predicate, returning an empty one when absent."""
        if not self._accept("KEYWORD", "WHERE"):
            return Predicate()
        terms = self._parse_term()
        while self._accept("KEYWORD", "AND"):
            terms.extend(self._parse_term())
        return Predicate(terms)

    def _parse_term(self):
        """parses one comparison, expanding BETWEEN into the two bounds it stands for."""
        column = self._identifier()
        if self._accept("KEYWORD", "BETWEEN"):
            low = self._literal()
            self._expect("KEYWORD", "AND")
            high = self._literal()
            return [Comparison(column, ">=", low), Comparison(column, "<=", high)]
        operator = self._expect("OP").value
        if operator not in COMPARISONS:
            raise SQLSyntaxError(f"unsupported operator {operator!r}")
        return [Comparison(column, operator, self._literal())]

    # -- leaves --

    def _identifier(self):
        """reads a table, column or index name."""
        token = self._peek()
        if token.kind == "IDENT":
            return self._next().value
        raise SQLSyntaxError(f"expected an identifier at position {token.position}, got {token.value!r}")

    def _literal(self):
        """reads a numeric, string or boolean literal and returns it as a python value."""
        token = self._next()
        if token.kind == "NUMBER":
            return float(token.value) if "." in token.value else int(token.value)
        if token.kind == "STRING":
            quote = token.value[0]
            return token.value[1:-1].replace(quote * 2, quote)
        if token.kind == "KEYWORD" and token.value in ("TRUE", "FALSE"):
            return token.value == "TRUE"
        raise SQLSyntaxError(f"expected a literal at position {token.position}, got {token.value!r}")
