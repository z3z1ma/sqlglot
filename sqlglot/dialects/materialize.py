from __future__ import annotations

from sqlglot import exp
from sqlglot.helper import seq_get
from sqlglot.dialects.postgres import Postgres

from sqlglot.tokens import TokenType
from sqlglot.transforms import (
    remove_unique_constraints,
    ctas_with_tmp_tables_to_create_tmp_view,
    preprocess,
)
import typing as t


class Materialize(Postgres):
    class Parser(Postgres.Parser):
        NO_PAREN_FUNCTION_PARSERS = {
            **Postgres.Parser.NO_PAREN_FUNCTION_PARSERS,
            "MAP": lambda self: self._parse_map(),
        }

        def _parse_map(self) -> exp.ToMap:
            if self._match(TokenType.L_PAREN):
                to_map = self.expression(exp.ToMap, this=self._parse_select())
                self._match_r_paren()
                return to_map

            if not self._match(TokenType.L_BRACKET):
                self.raise_error("Expecting [")
            entries = self._parse_csv(self._parse_map_entry)
            if not self._match(TokenType.R_BRACKET):
                self.raise_error("Expecting ]")
            return self.expression(exp.ToMap, this=self.expression(exp.Struct, expressions=entries))

        def _parse_map_entry(self) -> t.Optional[exp.PropertyEQ]:
            key = self._parse_conjunction()
            if not key:
                return None
            if not self._match(TokenType.FARROW):
                self.raise_error("Expected =>")
            value = self._parse_conjunction()
            return self.expression(exp.PropertyEQ, this=key, expression=value)

    class Generator(Postgres.Generator):
        SUPPORTS_CREATE_TABLE_LIKE = False

        TRANSFORMS = {
            **Postgres.Generator.TRANSFORMS,
            exp.AutoIncrementColumnConstraint: lambda self, e: "",
            exp.Create: preprocess(
                [
                    remove_unique_constraints,
                    ctas_with_tmp_tables_to_create_tmp_view,
                ]
            ),
            exp.GeneratedAsIdentityColumnConstraint: lambda self, e: "",
            exp.OnConflict: lambda self, e: "",
            exp.PrimaryKeyColumnConstraint: lambda self, e: "",
            exp.List: lambda self, e: self._list_sql(e),
            exp.ToMap: lambda self, e: self._to_map_sql(e),
        }

        def datatype_sql(self, expression: exp.DataType) -> str:
            if expression.is_type(exp.DataType.Type.LIST):
                if expression.expressions:
                    return f"{self.expressions(expression, flat=True)} LIST"
                return "LIST"
            if expression.is_type(exp.DataType.Type.MAP) and len(expression.expressions) == 2:
                key, value = expression.expressions
                return f"MAP[{self.sql(key)} => {self.sql(value)}]"
            return super().datatype_sql(expression)

        def _list_sql(self, expression: exp.List) -> str:
            if isinstance(seq_get(expression.expressions, 0), exp.Select):
                return self.func("LIST", seq_get(expression.expressions, 0))

            return f"{self.normalize_func('LIST')}[{self.expressions(expression, flat=True)}]"

        def _to_map_sql(self, expression: exp.ToMap) -> str:
            if isinstance(expression.this, exp.Select):
                return self.func("MAP", expression.this)

            entries = ", ".join(
                f"{self.sql(e.this)} => {self.sql(e.expression)}"
                for e in expression.this.expressions
            )
            return f"{self.normalize_func('MAP')}[{entries}]"
