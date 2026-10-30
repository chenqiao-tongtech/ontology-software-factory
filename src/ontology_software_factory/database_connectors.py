"""Schema-only PostgreSQL and MySQL connectors.

Connection strings are read from named environment variables. Explicit host allow-lists
and TLS are required; only information_schema metadata is queried.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

from .source_connectors import SourceAsset, SourceConnectorError, SourceScanResult, _asset_id


class _SQLSchemaConnector:
    source_type = "sql"

    def __init__(self, *, allowed_hosts: list[str], max_assets: int = 500):
        self.allowed_hosts = {host.strip().lower() for host in allowed_hosts if host.strip()}
        if not self.allowed_hosts:
            raise ValueError("at least one database host must be allow-listed")
        self.max_assets = max_assets

    def _connection_string(self, env_name: str) -> str:
        if not env_name or not env_name.replace("_", "").isalnum() or env_name[0].isdigit():
            raise SourceConnectorError("connectionEnv must be a valid environment variable name")
        value = os.getenv(env_name)
        if not value:
            raise SourceConnectorError(f"database connection environment variable is not set: {env_name}")
        return value

    def _validate_url(self, value: str, schemes: set[str]):
        parsed = urlparse(value)
        if parsed.scheme not in schemes or not parsed.hostname:
            raise SourceConnectorError("database connection URL has an unsupported scheme or missing host")
        if parsed.hostname.lower() not in self.allowed_hosts:
            raise SourceConnectorError("database host is not in the configured allow-list")
        return parsed


class PostgreSQLSchemaConnector(_SQLSchemaConnector):
    """PostgreSQL information_schema scanner using psycopg (optional dependency)."""

    source_type = "postgresql"

    def scan(self, source_id: str, location: str) -> SourceScanResult:
        value = self._connection_string(str(location))
        parsed = self._validate_url(value, {"postgres", "postgresql"})
        sslmode = parse_qs(parsed.query).get("sslmode", [""])[0].lower()
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise SourceConnectorError("PostgreSQL connection URL must specify sslmode=require, verify-ca, or verify-full")
        try:
            import psycopg
        except ImportError as exc:
            raise SourceConnectorError("install the postgres optional dependency to use this connector") from exc
        assets = []
        try:
            with psycopg.connect(value, connect_timeout=5) as connection:
                connection.execute("SET TRANSACTION READ ONLY")
                rows = connection.execute(
                    "SELECT table_schema, table_name, table_type FROM information_schema.tables "
                    "WHERE table_schema NOT IN ('pg_catalog','information_schema') "
                    "ORDER BY table_schema, table_name LIMIT %s", (self.max_assets,)
                ).fetchall()
                for schema, table, table_type in rows:
                    columns = connection.execute(
                        "SELECT column_name, data_type, is_nullable, ordinal_position "
                        "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
                        "ORDER BY ordinal_position", (schema, table)
                    ).fetchall()
                    locator = f"{schema}.{table}"
                    assets.append(SourceAsset(
                        asset_id=_asset_id(source_id, locator, "sql-table"),
                        source_id=source_id, kind="table" if table_type == "BASE TABLE" else "view",
                        name=str(table), locator=locator,
                        metadata={"schema": schema, "columns": [
                            {"name": c[0], "type": c[1], "nullable": c[2] == "YES", "ordinal": c[3]}
                            for c in columns
                        ], "database": "postgresql", "readOnly": True},
                    ))
        except SourceConnectorError:
            raise
        except Exception as exc:
            raise SourceConnectorError(f"PostgreSQL schema scan failed: {type(exc).__name__}") from exc
        return SourceScanResult(source_id, self.source_type, "connected", tuple(assets))


class MySQLSchemaConnector(_SQLSchemaConnector):
    """MySQL information_schema scanner using PyMySQL (optional dependency)."""

    source_type = "mysql"

    def scan(self, source_id: str, location: str) -> SourceScanResult:
        value = self._connection_string(str(location))
        parsed = self._validate_url(value, {"mysql", "mysql+pymysql"})
        if not parsed.path or parsed.path == "/":
            raise SourceConnectorError("MySQL URL must specify a database name")
        try:
            import pymysql
        except ImportError as exc:
            raise SourceConnectorError("install the mysql optional dependency to use this connector") from exc
        assets = []
        connection = None
        try:
            connection = pymysql.connect(
                host=parsed.hostname, port=parsed.port or 3306,
                user=unquote(parsed.username or ""), password=unquote(parsed.password or ""),
                database=unquote(parsed.path.lstrip("/")), connect_timeout=5,
                read_timeout=8, write_timeout=5, ssl={"check_hostname": True},
                autocommit=False, cursorclass=pymysql.cursors.DictCursor,
            )
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION TRANSACTION READ ONLY")
                cursor.execute(
                    "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM information_schema.tables "
                    "WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME LIMIT %s", (self.max_assets,)
                )
                tables = cursor.fetchall()
                for table in tables:
                    cursor.execute(
                        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, ORDINAL_POSITION "
                        "FROM information_schema.columns WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
                        "ORDER BY ORDINAL_POSITION", (table["TABLE_SCHEMA"], table["TABLE_NAME"])
                    )
                    columns = cursor.fetchall()
                    locator = f'{table["TABLE_SCHEMA"]}.{table["TABLE_NAME"]}'
                    assets.append(SourceAsset(
                        asset_id=_asset_id(source_id, locator, "sql-table"),
                        source_id=source_id,
                        kind="table" if table["TABLE_TYPE"] == "BASE TABLE" else "view",
                        name=str(table["TABLE_NAME"]), locator=locator,
                        metadata={"schema": table["TABLE_SCHEMA"], "database": "mysql", "readOnly": True,
                            "columns": [
                                {"name": c["COLUMN_NAME"], "type": c["DATA_TYPE"],
                                 "nullable": c["IS_NULLABLE"] == "YES", "ordinal": c["ORDINAL_POSITION"]}
                                for c in columns
                            ]},
                    ))
            connection.rollback()
        except SourceConnectorError:
            raise
        except Exception as exc:
            raise SourceConnectorError(f"MySQL schema scan failed: {type(exc).__name__}") from exc
        finally:
            if connection is not None:
                connection.close()
        return SourceScanResult(source_id, self.source_type, "connected", tuple(assets))
