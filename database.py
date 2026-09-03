import sqlite3


def create_database():
    connection = sqlite3.connect("helpdesk.db")

    connection.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open',
            resolution TEXT DEFAULT ''
        )
    """)

    # Add resolution column to an existing database if it doesn't have it
    columns = connection.execute(
        "PRAGMA table_info(tickets)"
    ).fetchall()

    column_names = [column[1] for column in columns]

    if "resolution" not in column_names:
        connection.execute(
            "ALTER TABLE tickets ADD COLUMN resolution TEXT DEFAULT ''"
        )

    connection.commit()
    connection.close()


if __name__ == "__main__":
    create_database()