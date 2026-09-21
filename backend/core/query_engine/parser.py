"""Parser descendente del subconjunto SQL del Entregable 1."""

from backend.core.catalog.schema_manager import ColumnDef
from .query_models import ParsedQuery, Condition
from .tokenizer import tokenize


class SQLParser:
    def _peek(self, value):
        return (
            self.position < len(self.tokens)
            and self.tokens[self.position][1].upper() == value
        )

    def _take(self):
        if self.position == len(self.tokens):
            raise ValueError("SQL incompleto")
        token = self.tokens[self.position]
        self.position += 1
        return token

    def _expect(self, value):
        if not self._peek(value):
            raise ValueError(f"Se esperaba {value}")
        return self._take()[1]

    def _identifier(self):
        kind, value = self._take()
        if kind != "ID":
            raise ValueError("Se esperaba un identificador")
        return value.lower()

    def _literal(self):
        kind, value = self._take()
        if kind == "STRING":
            return value[1:-1].replace("''", "'")
        if kind == "NUMBER":
            return float(value) if any(c in value.lower() for c in ".e") else int(value)
        raise ValueError("Se esperaba un número o texto entre comillas simples")

    # ============================================================
    # PARTE IMPORTANTE PARA EXPOSICION: TOKENS -> PARSED QUERY
    # ============================================================
    def parse(self, sql):
        self.tokens, self.position = tokenize(sql), 0
        command = self._take()[1].upper()
        if command == "CREATE":
            query = self._create()
        elif command == "DROP":
            self._expect("TABLE")
            query = ParsedQuery("DROP_TABLE", self._identifier())
        elif command == "INSERT":
            self._expect("INTO")
            query = ParsedQuery("INSERT", self._identifier())
            self._expect("VALUES")
            self._expect("(")
            query.values.append(self._literal())
            while self._peek(","):
                self._take()
                query.values.append(self._literal())
            self._expect(")")
        elif command in ("SELECT", "DELETE"):
            projection = ["*"]
            if command == "SELECT":
                if self._peek("*"):
                    self._take()
                else:
                    projection = [self._identifier()]
                    while self._peek(","):
                        self._take()
                        projection.append(self._identifier())
            self._expect("FROM")
            query = ParsedQuery(command, self._identifier(), projection=projection)
            if self._peek("WHERE"):
                self._take()
                while True:
                    column = self._identifier()
                    operator = self._take()[1]
                    if operator not in ("=", ">=", "<=", ">", "<", "!=", "<>"):
                        raise ValueError("Operador WHERE no soportado")
                    query.conditions.append(
                        Condition(column, operator, self._literal())
                    )
                    if not self._peek("AND"):
                        break
                    self._take()
        else:
            raise ValueError(f"Sentencia SQL no soportada: {command}")
        if self._peek(";"):
            self._take()
        if self.position != len(self.tokens):
            raise ValueError("Sintaxis no soportada o más de una sentencia SQL")
        return query

    def _create(self):
        if self._peek("TABLE"):
            self._take()
            query = ParsedQuery("CREATE_TABLE", self._identifier())
            self._expect("(")
            while True:
                name, dtype = self._identifier(), self._take()[1].upper()
                if dtype == "CHAR":
                    self._expect("(")
                    size = self._literal()
                    if type(size) is not int or size <= 0:
                        raise ValueError("CHAR requiere longitud entera positiva")
                    self._expect(")")
                    dtype = f"CHAR({size})"
                elif dtype not in ("INT", "FLOAT"):
                    raise ValueError("Tipo SQL no soportado")
                primary = self._peek("PRIMARY")
                if primary:
                    self._take()
                    self._expect("KEY")
                query.columns.append(ColumnDef(name, dtype, primary))
                if not self._peek(","):
                    break
                self._take()
            self._expect(")")
            self._expect("USING")
            query.organization = self._take()[1].upper()
            if query.organization not in ("HEAP", "SEQUENTIAL"):
                raise ValueError("USING requiere HEAP o SEQUENTIAL")
            return query
        self._expect("INDEX")
        name = self._identifier()
        self._expect("ON")
        table = self._identifier()
        self._expect("(")
        column = self._identifier()
        self._expect(")")
        self._expect("USING")
        kind = self._take()[1].upper()
        if kind not in ("BTREE", "HASH"):
            raise ValueError("Índice debe ser BTREE o HASH")
        return ParsedQuery(
            "CREATE_INDEX", table, index_name=name, index_kind=kind, index_column=column
        )
