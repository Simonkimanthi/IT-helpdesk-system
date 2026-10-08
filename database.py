from database_connection import get_database


def add_column_if_missing(connection, table, column, definition):
    if connection.is_postgres:
        columns = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ?
            """,
            (table,)
        ).fetchall()
        column_names = {
            column["column_name"]
            for column in columns
        }
    else:
        columns = connection.execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
        column_names = {
            column["name"]
            for column in columns
        }

    if column not in column_names:
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def create_database():
    connection = get_database()
    primary_key = (
        "SERIAL PRIMARY KEY"
        if connection.is_postgres
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )

    # -------------------------------------------------
    # Tickets table
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS tickets (
            id {primary_key},
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Medium',
            status TEXT NOT NULL DEFAULT 'Open',
            resolution TEXT DEFAULT ''
        )
    """)

    # -------------------------------------------------
    # Upgrade existing tickets table safely
    # -------------------------------------------------
    add_column_if_missing(
        connection,
        "tickets",
        "phone",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "department",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "location",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "category",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "equipment",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "assigned_to",
        "INTEGER"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "created_at",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "updated_at",
        "TEXT DEFAULT ''"
    )

    add_column_if_missing(
        connection,
        "tickets",
        "resolved_at",
        "TEXT DEFAULT ''"
    )

    # -------------------------------------------------
    # ICT staff accounts
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS ict_staff (
            id {primary_key},
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'technician',
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # -------------------------------------------------
    # ICT staff coverage areas
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS staff_coverage (
            id {primary_key},
            staff_id INTEGER NOT NULL,
            coverage_area TEXT NOT NULL,
            FOREIGN KEY (staff_id) REFERENCES ict_staff(id)
        )
    """)

    # -------------------------------------------------
    # Staff absences and temporary coverage handovers
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS staff_absences (
            id {primary_key},
            staff_id INTEGER NOT NULL,
            coverage_area TEXT NOT NULL,
            substitute_staff_id INTEGER,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            reason TEXT DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (staff_id) REFERENCES ict_staff(id),
            FOREIGN KEY (substitute_staff_id) REFERENCES ict_staff(id)
        )
    """)

    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_staff_absences_area_dates
        ON staff_absences (coverage_area, active, start_date, end_date)
    """)

    # -------------------------------------------------
    # Hospital work areas / sections
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS hospital_sections (
            id {primary_key},
            name TEXT NOT NULL UNIQUE,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)

    # -------------------------------------------------
    # Initial hospital work areas
    # -------------------------------------------------
    initial_sections = [
        "Main Lab",
        "Lab",
        "Radiology",
        "Radiology Billing Point",
        "Maternity / Ward Seven",
        "Maternity SHA Point",
        "Maternity Billing Point",
        "Eye Clinic",
        "Gynecology",
        "Palliative Care",
        "Amenity",
        "Outpatient Department (OPD)",
        "Inpatient / General Wards",
        "Pharmacy",
        "Pharmacy Store",
        "Laboratory Reception / Sample Collection",
        "Dental Clinic",
        "Theatre / Operating Theatre",
        "Emergency / Casualty",
        "Medical Records",
        "Registration / Reception",
        "SHA Point",
        "Billing Point",
        "Administration",
        "Human Resources",
        "Procurement / Stores",
        "Mortuary",
        "Nutrition / Catering",
        "Physiotherapy",
        "MCH / Maternal & Child Health",
        "Antenatal Clinic",
        "Postnatal Clinic",
        "Immunization / Child Welfare",
        "TB Clinic",
        "HIV / Comprehensive Care Centre",
        "Dermatology",
        "ENT Clinic",
        "Orthopaedic Clinic",
        "Surgical Clinic",
        "Medical Clinic",
        "Pediatric Clinic",
        "Mental Health Clinic",
        "Ambulance / Transport",
        "ICT Department",
        "Main Store"
    ]

    existing_sections = connection.execute("""
        SELECT COUNT(*) AS total
        FROM hospital_sections
    """).fetchone()

    if existing_sections["total"] == 0:
        for section in initial_sections:
            connection.execute("""
                INSERT INTO hospital_sections (name, active)
                VALUES (?, 1)
            """, (section,))

    # -------------------------------------------------
    # Ticket history
    # -------------------------------------------------
    connection.execute(f"""
        CREATE TABLE IF NOT EXISTS ticket_history (
            id {primary_key},
            ticket_id INTEGER NOT NULL,
            staff_id INTEGER,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id),
            FOREIGN KEY (staff_id) REFERENCES ict_staff(id)
        )
    """)

    add_column_if_missing(
        connection,
        "ticket_history",
        "staff_name",
        "TEXT DEFAULT ''"
    )

    connection.execute("""
        UPDATE ticket_history
        SET staff_name = (
            SELECT name
            FROM ict_staff
            WHERE ict_staff.id = ticket_history.staff_id
        )
        WHERE COALESCE(staff_name, '') = ''
          AND staff_id IS NOT NULL
    """)

    # -------------------------------------------------
    # Create default ICT administrator
    # -------------------------------------------------
    existing_admin = connection.execute("""
        SELECT id
        FROM ict_staff
        WHERE username = ?
    """, ("admin",)).fetchone()

    if existing_admin is None:
        connection.execute("""
            INSERT INTO ict_staff
            (name, username, password, role)
            VALUES (?, ?, ?, ?)
        """, (
            "ICT Administrator",
            "admin",
            "admin123",
            "admin"
        ))

    connection.commit()
    connection.close()


# -------------------------------------------------
# Run database setup
# -------------------------------------------------
if __name__ == "__main__":
    create_database()
    print("Hospital ICT Support System database is ready.")