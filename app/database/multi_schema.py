"""Multi-schema support for SQL Server.

LangChain's `SQLDatabase` reflects a single schema by default, which on SQL
Server resolves to the connection's default schema — almost always `dbo`.
Real-world SQL Server databases (AdventureWorks very much included) spread
their actual business tables across several schemas (`Production`, `Sales`,
`Person`, `HumanResources`, `Purchasing`, ...), so a plain single-schema
reflection leaves the agent able to see only a handful of housekeeping
tables and none of the data anyone actually asks about.

`MultiSchemaSQLDatabase` reflects every relevant schema into one shared
catalog so schema-qualified names (`Production.Product`) both show up in
`get_usable_table_names()` and resolve correctly in `get_table_info()`.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from langchain_community.utilities.sql_database import SQLDatabase
from sqlalchemy import MetaData, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

# Built-in SQL Server schemas that are never useful to a natural-language
# business-data agent. Excluded from auto-discovery.
SYSTEM_SCHEMAS = {
    "sys",
    "information_schema",
    "guest",
    "db_owner",
    "db_accessadmin",
    "db_securityadmin",
    "db_ddladmin",
    "db_backupoperator",
    "db_datareader",
    "db_datawriter",
    "db_denydatareader",
    "db_denydatawriter",
}


def discover_business_schemas(engine: Engine) -> List[str]:
    """Return every schema in the database except SQL Server's built-in
    system/role schemas, so the agent sees real business tables by default
    without needing per-database configuration.
    """
    inspector = inspect(engine)
    return sorted(
        s for s in inspector.get_schema_names() if s.lower() not in SYSTEM_SCHEMAS
    )


class MultiSchemaSQLDatabase(SQLDatabase):
    """A `SQLDatabase` that reflects tables across multiple schemas instead
    of just the connection's default one.
    """

    def __init__(self, engine: Engine, schemas: Iterable[str], **kwargs):
        self._schemas: List[str] = list(schemas)
        # Skip the base class's own (single-schema) reflection — we replace
        # `_metadata` with our own multi-schema reflection right after.
        kwargs.setdefault("lazy_table_reflection", True)
        super().__init__(engine, schema=None, **kwargs)

        metadata = MetaData()
        for schema in self._schemas:
            metadata.reflect(bind=engine, schema=schema, views=self._view_support)
        self._metadata = metadata

        self._all_tables = set(metadata.tables.keys())
        if self._include_tables:
            missing = self._include_tables - self._all_tables
            if missing:
                raise ValueError(f"include_tables {missing} not found in database")
        self._usable_tables = (
            self._include_tables if self._include_tables else self._all_tables - self._ignore_tables
        )

    def get_usable_table_names(self) -> Iterable[str]:
        if not hasattr(self, "_usable_tables"):
            # Called once during the base class's own __init__, before our
            # multi-schema reflection has run — fall back to whatever the
            # base class discovered for its single default schema.
            return sorted(getattr(self, "_all_tables", set()))
        return sorted(self._usable_tables)

    def get_table_info(self, table_names: Optional[List[str]] = None) -> str:
        all_table_names = list(self.get_usable_table_names())
        if table_names is not None:
            missing = set(table_names) - set(all_table_names)
            if missing:
                raise ValueError(f"table_names {missing} not found in database")
            all_table_names = table_names

        rendered = []
        for qualified_name in sorted(all_table_names):
            table = self._metadata.tables.get(qualified_name)
            if table is None:
                continue
            create_table = str(CreateTable(table).compile(self._engine)).rstrip()
            info = create_table
            if self._sample_rows_in_table_info:
                info += "\n\n/*\n" + self._get_sample_rows(table) + "\n*/"
            rendered.append(info)
        return "\n\n".join(rendered)
