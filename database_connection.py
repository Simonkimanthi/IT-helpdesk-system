import os
import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().with_name("helpdesk.db")


class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _hybrid_row(cursor):
    column_names = [
        column.name
        for column in (cursor.description or ())
    ]

    def create_row(values):
        return HybridRow(zip(column_names, values))

    return create_row


class DatabaseConnection:
    def __init__(self, connection, is_postgres):
        self._connection = connection
        self.is_postgres = is_postgres

    def execute(self, query, parameters=()):
        if self.is_postgres:
            query = query.replace("?", "%s")
        return self._connection.execute(query, parameters)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def get_database():
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        import psycopg

        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://"):]

        connection = psycopg.connect(
            database_url,
            row_factory=_hybrid_row
        )
        return DatabaseConnection(connection, is_postgres=True)

    connection = sqlite3.connect(str(DATABASE_PATH))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return DatabaseConnection(connection, is_postgres=False)
