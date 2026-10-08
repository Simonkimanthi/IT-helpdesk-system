from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    url_for,
    jsonify
)

import sqlite3
import re
from datetime import date, datetime, timedelta


# =========================================================
# APPLICATION CONFIGURATION
# =========================================================

app = Flask(__name__)

app.secret_key = "hospital-ict-support-secret-key"

DATABASE_NAME = "helpdesk.db"


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_database():
    connection = sqlite3.connect(DATABASE_NAME)

    connection.row_factory = sqlite3.Row

    connection.execute("PRAGMA foreign_keys = ON")

    return connection


# =========================================================
# GENERAL HELPERS
# =========================================================

def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_text(value):
    if value is None:
        return ""

    return str(value).strip()


def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.is_json
    )


def json_success(message, **extra):
    response = {
        "success": True,
        "message": message
    }

    response.update(extra)

    return jsonify(response)


def json_error(message, status=400, **extra):
    response = {
        "success": False,
        "message": message
    }

    response.update(extra)

    return jsonify(response), status


def ticket_number(ticket_id):
    return f"KCRH-ICT-{ticket_id:05d}"


# =========================================================
# AUTHENTICATION
# =========================================================

def get_current_staff():

    staff_id = session.get("staff_id")

    if not staff_id:
        return None

    connection = get_database()

    staff = connection.execute(
        """
        SELECT
            id,
            name,
            username,
            role,
            active
        FROM ict_staff
        WHERE id = ?
        """,
        (staff_id,)
    ).fetchone()

    connection.close()

    if not staff:
        session.clear()
        return None

    if not staff["active"]:
        session.clear()
        return None

    return staff


def is_logged_in():

    return get_current_staff() is not None


def is_admin():

    staff = get_current_staff()

    return (
        staff is not None
        and staff["role"] == "admin"
    )


# =========================================================
# TICKET HISTORY
# =========================================================

def add_history(
    connection,
    ticket_id,
    staff_name,
    action,
    details=""
):

    connection.execute(
        """
        INSERT INTO ticket_history (
            ticket_id,
            staff_name,
            action,
            details,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            ticket_id,
            staff_name,
            action,
            details,
            current_time()
        )
    )


# =========================================================
# HOSPITAL SECTIONS
# =========================================================

def get_active_sections():

    connection = get_database()

    sections = connection.execute(
        """
        SELECT
            id,
            name
        FROM hospital_sections
        WHERE active = 1
        ORDER BY name ASC
        """
    ).fetchall()

    connection.close()

    return sections


# =========================================================
# TECHNICIAN COVERAGE
# =========================================================

def get_technician_coverage(
    connection,
    staff_id
):

    coverage = connection.execute(
        """
        SELECT coverage_area
        FROM staff_coverage
        WHERE staff_id = ?

        UNION

        SELECT absence.coverage_area
        FROM staff_absences absence
        INNER JOIN ict_staff absent_staff
            ON absent_staff.id = absence.staff_id
        WHERE absence.substitute_staff_id = ?
          AND absence.active = 1
          AND absent_staff.active = 1
          AND date('now', 'localtime')
              BETWEEN absence.start_date AND absence.end_date
          AND NOT EXISTS (
              SELECT 1
              FROM staff_absences own_absence
              WHERE own_absence.staff_id = ?
                AND own_absence.coverage_area = absence.coverage_area
                AND own_absence.active = 1
                AND date('now', 'localtime')
                    BETWEEN own_absence.start_date AND own_absence.end_date
          )

        ORDER BY coverage_area ASC
        """,
        (staff_id, staff_id, staff_id)
    ).fetchall()

    return [
        row["coverage_area"]
        for row in coverage
    ]


# =========================================================
# CHECK TECHNICIAN ACCESS TO TICKET
# =========================================================

def technician_can_access_ticket(
    connection,
    staff_id,
    ticket
):

    # A technician can always access a ticket
    # directly assigned to them.

    if ticket["assigned_to"] == staff_id:
        return True

    # Otherwise, they can access tickets from
    # their assigned coverage areas.

    coverage = connection.execute(
        """
        SELECT 1
        FROM staff_coverage
        WHERE staff_id = ?
          AND coverage_area = ?

        UNION

        SELECT 1
        FROM staff_absences absence
        INNER JOIN ict_staff absent_staff
            ON absent_staff.id = absence.staff_id
        WHERE absence.substitute_staff_id = ?
          AND absence.coverage_area = ?
          AND absence.active = 1
          AND absent_staff.active = 1
          AND date('now', 'localtime')
              BETWEEN absence.start_date AND absence.end_date
          AND NOT EXISTS (
              SELECT 1
              FROM staff_absences own_absence
              WHERE own_absence.staff_id = ?
                AND own_absence.coverage_area = absence.coverage_area
                AND own_absence.active = 1
                AND date('now', 'localtime')
                    BETWEEN own_absence.start_date AND own_absence.end_date
          )

        LIMIT 1
        """,
        (
            staff_id,
            ticket["department"],
            staff_id,
            ticket["department"],
            staff_id
        )
    ).fetchone()

    return coverage is not None


# =========================================================
# AUTOMATIC TICKET ASSIGNMENT
# =========================================================

def find_automatic_assignee(
    connection,
    department
):

    today = date.today().isoformat()

    technician = connection.execute(
        """
        SELECT
            eligible.id,
            eligible.name,
            (
                SELECT COUNT(*)
                FROM tickets active_ticket
                WHERE active_ticket.assigned_to = eligible.id
                  AND active_ticket.status IN ('Assigned', 'In Progress')
            ) AS active_ticket_count,
            eligible.is_substitute
        FROM (
            SELECT DISTINCT
                s.id,
                s.name,
                0 AS is_substitute
            FROM ict_staff s
            INNER JOIN staff_coverage coverage
                ON coverage.staff_id = s.id
            WHERE s.active = 1
              AND s.role = 'technician'
              AND coverage.coverage_area = ?

            UNION ALL

            SELECT DISTINCT
                substitute.id,
                substitute.name,
                1 AS is_substitute
            FROM staff_absences absence
            INNER JOIN ict_staff absent_staff
                ON absent_staff.id = absence.staff_id
            INNER JOIN ict_staff substitute
                ON substitute.id = absence.substitute_staff_id
            WHERE absence.coverage_area = ?
              AND absence.active = 1
              AND absent_staff.active = 1
              AND substitute.active = 1
              AND substitute.role = 'technician'
              AND ? BETWEEN absence.start_date AND absence.end_date
        ) eligible
        WHERE NOT EXISTS (
            SELECT 1
            FROM staff_absences unavailable
            WHERE unavailable.staff_id = eligible.id
              AND unavailable.coverage_area = ?
              AND unavailable.active = 1
              AND ? BETWEEN unavailable.start_date AND unavailable.end_date
        )
        ORDER BY
            eligible.is_substitute DESC,
            active_ticket_count ASC,
            eligible.id ASC

        LIMIT 1
        """,
        (department, department, today, department, today)
    ).fetchone()

    if not technician:
        return None

    return technician["id"]


# =========================================================
# HOME / SUPPORT REQUEST FORM
# =========================================================

@app.route("/")
def home():

    sections = get_active_sections()

    return render_template(
        "index.html",
        sections=sections
    )


# =========================================================
# SUBMIT SUPPORT REQUEST
# =========================================================

@app.route(
    "/submit",
    methods=["POST"]
)
def submit_ticket():

    name = normalize_text(
        request.form.get("name")
    )

    phone = normalize_text(
        request.form.get("phone")
    )

    email = normalize_text(
        request.form.get("email")
    )

    department = normalize_text(
        request.form.get("department")
    )

    location = normalize_text(
        request.form.get("location")
    )

    equipment = normalize_text(
        request.form.get("equipment")
    )

    category = normalize_text(
        request.form.get("category")
    )

    subject = normalize_text(
        request.form.get("subject")
    )

    description = normalize_text(
        request.form.get("description")
    )


    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if not name:
        return (
            "Requester name is required.",
            400
        )

    if not department:
        return (
            "Department / Work Area is required.",
            400
        )

    if not subject:
        return (
            "Problem subject is required.",
            400
        )

    if not description:
        return (
            "Problem description is required.",
            400
        )


    # -----------------------------------------------------
    # EMAIL VALIDATION
    # -----------------------------------------------------

    if email:

        email_pattern = (
            r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        )

        if not re.match(
            email_pattern,
            email
        ):
            return (
                "Please enter a valid email address.",
                400
            )


    # -----------------------------------------------------
    # CHECK DEPARTMENT / WORK AREA
    # -----------------------------------------------------

    connection = get_database()

    section = connection.execute(
        """
        SELECT id
        FROM hospital_sections
        WHERE name = ?
          AND active = 1
        """,
        (department,)
    ).fetchone()

    if not section:

        connection.close()

        return (
            "The selected Department / Work Area is not available.",
            400
        )


    # -----------------------------------------------------
    # AUTOMATIC ASSIGNMENT
    # -----------------------------------------------------

    assigned_to = find_automatic_assignee(
        connection,
        department
    )


    if assigned_to:

        status = "Assigned"

    else:

        status = "Open"


    priority = "Medium"


    # -----------------------------------------------------
    # CREATE TICKET
    # -----------------------------------------------------

    cursor = connection.execute(
        """
        INSERT INTO tickets (
            name,
            phone,
            email,
            department,
            location,
            equipment,
            category,
            subject,
            description,
            priority,
            status,
            assigned_to,
            created_at,
            updated_at
        )

        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            name,
            phone,
            email,
            department,
            location,
            equipment,
            category,
            subject,
            description,
            priority,
            status,
            assigned_to,
            current_time(),
            current_time()
        )
    )


    ticket_id = cursor.lastrowid


    # -----------------------------------------------------
    # HISTORY
    # -----------------------------------------------------

    add_history(
        connection,
        ticket_id,
        name,
        "Request Submitted",
        "ICT support request submitted."
    )


    if assigned_to:

        assigned_staff = connection.execute(
            """
            SELECT name
            FROM ict_staff
            WHERE id = ?
            """,
            (assigned_to,)
        ).fetchone()

        if assigned_staff:

            add_history(
                connection,
                ticket_id,
                "System",
                "Automatically Assigned",
                f"Assigned to {assigned_staff['name']} based on work-area coverage and availability."
            )


    connection.commit()

    connection.close()


    # -----------------------------------------------------
    # CONFIRMATION
    # -----------------------------------------------------

    return render_template(
        "success.html",
        display_ticket_number=ticket_number(ticket_id),
        ticket_id=ticket_id,
        status=status,
        assigned=bool(assigned_to)
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "GET":

        if is_logged_in():

            return redirect(
                url_for("dashboard")
            )

        return render_template(
            "login.html"
        )


    username = normalize_text(
        request.form.get("username")
    )

    password = normalize_text(
        request.form.get("password")
    )


    if not username or not password:

        return render_template(
            "login.html",
            error="Username and password are required."
        )


    connection = get_database()

    staff = connection.execute(
        """
        SELECT
            id,
            name,
            username,
            password,
            role,
            active
        FROM ict_staff
        WHERE username = ?
        """,
        (username,)
    ).fetchone()

    connection.close()


    if not staff:

        return render_template(
            "login.html",
            error="Invalid username or password."
        )


    if not staff["active"]:

        return render_template(
            "login.html",
            error="This account is inactive."
        )


    if staff["password"] != password:

        return render_template(
            "login.html",
            error="Invalid username or password."
        )


    session.clear()

    session["staff_id"] = staff["id"]


    return redirect(
        url_for("dashboard")
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("login")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    staff = get_current_staff()

    if not staff:

        return redirect(
            url_for("login")
        )


    connection = get_database()

    if staff["role"] == "admin":

        tickets = connection.execute(
            """
            SELECT
                t.*,
                s.name AS assigned_staff_name

            FROM tickets t

            LEFT JOIN ict_staff s
                ON s.id = t.assigned_to

            ORDER BY
                t.id DESC
            """
        ).fetchall()

        coverage = []

    else:

        coverage = get_technician_coverage(
            connection,
            staff["id"]
        )

        if coverage:
            placeholders = ",".join(
                ["?"] * len(coverage)
            )

            tickets = connection.execute(
                f"""
                SELECT
                    t.*,
                    s.name AS assigned_staff_name

                FROM tickets t

                LEFT JOIN ict_staff s
                    ON s.id = t.assigned_to

                WHERE t.department IN (
                    {placeholders}
                )

                ORDER BY
                    t.id DESC
                """,
                coverage
            ).fetchall()
        else:
            tickets = []


    connection.close()

    today = date.today()
    period_options = {
        "today": "Today",
        "yesterday": "Yesterday",
        "last7": "Last 7 days",
        "month": "This month",
        "all": "All history",
        "custom": "Custom range"
    }
    period = normalize_text(
        request.args.get("period")
    ).lower()
    if period not in period_options:
        period = "today"

    start_date_value = normalize_text(
        request.args.get("start_date")
    )
    end_date_value = normalize_text(
        request.args.get("end_date")
    )
    custom_start = None
    custom_end = None
    if period == "custom":
        try:
            custom_start = date.fromisoformat(start_date_value)
            custom_end = date.fromisoformat(end_date_value)
        except ValueError:
            return (
                "Select valid start and end dates for the custom range.",
                400
            )

        if custom_start > custom_end:
            return (
                "The custom range end date cannot be before its start date.",
                400
            )

    def ticket_matches_period(ticket):
        if period == "all":
            return True

        created_at = str(ticket["created_at"] or "")[:10]
        try:
            created_date = date.fromisoformat(created_at)
        except ValueError:
            return False

        if period == "today":
            return created_date == today
        if period == "yesterday":
            return created_date == today - timedelta(days=1)
        if period == "last7":
            return today - timedelta(days=6) <= created_date <= today
        if period == "custom":
            return custom_start <= created_date <= custom_end
        return created_date.year == today.year and created_date.month == today.month

    period_tickets = [
        ticket
        for ticket in tickets
        if ticket_matches_period(ticket)
    ]

    total_tickets = len(period_tickets)
    open_tickets = sum(
        ticket["status"] == "Open"
        for ticket in period_tickets
    )
    assigned_tickets = sum(
        ticket["status"] == "Assigned"
        for ticket in period_tickets
    )
    in_progress_tickets = sum(
        ticket["status"] == "In Progress"
        for ticket in period_tickets
    )
    resolved_tickets = sum(
        ticket["status"] == "Resolved"
        for ticket in period_tickets
    )
    high_priority_tickets = sum(
        ticket["priority"] in ("High", "Critical")
        for ticket in period_tickets
    )

    search = normalize_text(
        request.args.get("search")
    )

    if search:
        search_lower = search.lower()
        tickets = [
            ticket
            for ticket in period_tickets
            if (
                search_lower in str(
                    ticket["name"] or ""
                ).lower()

                or search_lower in str(
                    ticket["subject"] or ""
                ).lower()

                or search_lower in str(
                    ticket["description"] or ""
                ).lower()

                or search_lower in str(
                    ticket["department"] or ""
                ).lower()

                or search_lower in str(
                    ticket["status"] or ""
                ).lower()

                or search_lower in str(
                    ticket["priority"] or ""
                ).lower()

                or search_lower in ticket_number(
                    ticket["id"]
                ).lower()
            )
        ]
    else:
        tickets = period_tickets


    return render_template(
        "dashboard.html",

        staff=staff,

        tickets=tickets,

        total_tickets=total_tickets,

        open_tickets=open_tickets,

        assigned_tickets=assigned_tickets,

        in_progress_tickets=in_progress_tickets,

        resolved_tickets=resolved_tickets,

        high_priority_tickets=high_priority_tickets,

        search=search,

        coverage=coverage,

        period=period,

        period_options=period_options,

        start_date=start_date_value,

        end_date=end_date_value
    )


# =========================================================
# TICKET DETAILS
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>"
)
def ticket_details(ticket_id):

    staff = get_current_staff()

    if not staff:

        return redirect(
            url_for("login")
        )


    connection = get_database()


    ticket = connection.execute(
        """
        SELECT
            t.*,
            s.name AS assigned_staff_name

        FROM tickets t

        LEFT JOIN ict_staff s
            ON s.id = t.assigned_to

        WHERE t.id = ?
        """,
        (ticket_id,)
    ).fetchone()


    if not ticket:

        connection.close()

        return (
            "Ticket not found.",
            404
        )


    # -----------------------------------------------------
    # TECHNICIAN ACCESS CONTROL
    # -----------------------------------------------------

    if staff["role"] != "admin":

        allowed = technician_can_access_ticket(
            connection,
            staff["id"],
            ticket
        )

        if not allowed:

            connection.close()

            return (
                "Access denied.",
                403
            )


    history = connection.execute(
        """
        SELECT
            id,
            staff_name,
            action,
            details,
            created_at

        FROM ticket_history

        WHERE ticket_id = ?

        ORDER BY
            id DESC
        """,
        (ticket_id,)
    ).fetchall()


    ict_staff = connection.execute(
        """
        SELECT
            id,
            name,
            username,
            role,
            active

        FROM ict_staff

        WHERE active = 1

        ORDER BY
            name ASC
        """
    ).fetchall()


    connection.close()


    return render_template(
        "ticket.html",

        staff=staff,

        ticket=ticket,

        history=history,

        ict_staff=ict_staff
    )


# =========================================================
# GET TICKET FOR UPDATE
# =========================================================

def get_ticket_for_update(ticket_id):

    staff = get_current_staff()


    if not staff:

        return None, None, None


    connection = get_database()


    ticket = connection.execute(
        """
        SELECT *
        FROM tickets
        WHERE id = ?
        """,
        (ticket_id,)
    ).fetchone()


    if not ticket:

        connection.close()

        return None, staff, connection


    if staff["role"] != "admin":

        allowed = technician_can_access_ticket(
            connection,
            staff["id"],
            ticket
        )

        if not allowed:

            connection.close()

            return None, staff, None


    return ticket, staff, connection


# =========================================================
# UPDATE STATUS
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/status",
    methods=["POST"]
)
def update_status(ticket_id):

    ticket, staff, connection = (
        get_ticket_for_update(ticket_id)
    )


    if not staff:

        return redirect(
            url_for("login")
        )


    if not ticket:

        return (
            "Access denied or ticket not found.",
            403
        )


    status = normalize_text(
        request.form.get("status")
    )


    allowed_statuses = [
        "Open",
        "Assigned",
        "In Progress",
        "Resolved"
    ]


    if status not in allowed_statuses:

        connection.close()

        return (
            "Invalid status.",
            400
        )


    connection.execute(
        """
        UPDATE tickets

        SET
            status = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            status,
            current_time(),
            ticket_id
        )
    )


    add_history(
        connection,
        ticket_id,
        staff["name"],
        "Status Updated",
        f"Status changed to {status}."
    )


    connection.commit()

    connection.close()


    if wants_json_response():

        return json_success(
            "Ticket status updated successfully."
        )


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# UPDATE PRIORITY
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/priority",
    methods=["POST"]
)
def update_priority(ticket_id):

    ticket, staff, connection = (
        get_ticket_for_update(ticket_id)
    )


    if not staff:

        return redirect(
            url_for("login")
        )


    if not ticket:

        return (
            "Access denied or ticket not found.",
            403
        )


    priority = normalize_text(
        request.form.get("priority")
    )


    allowed_priorities = [
        "Low",
        "Medium",
        "High",
        "Critical"
    ]


    if priority not in allowed_priorities:

        connection.close()

        return (
            "Invalid priority.",
            400
        )


    connection.execute(
        """
        UPDATE tickets

        SET
            priority = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            priority,
            current_time(),
            ticket_id
        )
    )


    add_history(
        connection,
        ticket_id,
        staff["name"],
        "Priority Updated",
        f"Priority changed to {priority}."
    )


    connection.commit()

    connection.close()


    if wants_json_response():

        return json_success(
            "Ticket priority updated successfully."
        )


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# UPDATE CATEGORY
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/category",
    methods=["POST"]
)
def update_category(ticket_id):

    ticket, staff, connection = (
        get_ticket_for_update(ticket_id)
    )


    if not staff:

        return redirect(
            url_for("login")
        )


    if not ticket:

        return (
            "Access denied or ticket not found.",
            403
        )


    category = normalize_text(
        request.form.get("category")
    )


    connection.execute(
        """
        UPDATE tickets

        SET
            category = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            category,
            current_time(),
            ticket_id
        )
    )


    add_history(
        connection,
        ticket_id,
        staff["name"],
        "Category Updated",
        f"Category changed to {category or 'Uncategorized'}."
    )


    connection.commit()

    connection.close()


    if wants_json_response():

        return json_success(
            "Ticket category updated successfully."
        )


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# ADD RESOLUTION
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/resolution",
    methods=["POST"]
)
def update_resolution(ticket_id):

    ticket, staff, connection = (
        get_ticket_for_update(ticket_id)
    )


    if not staff:

        return redirect(
            url_for("login")
        )


    if not ticket:

        return (
            "Access denied or ticket not found.",
            403
        )


    resolution = normalize_text(
        request.form.get("resolution")
    )


    if not resolution:

        connection.close()

        return (
            "Resolution notes are required.",
            400
        )


    connection.execute(
        """
        UPDATE tickets

        SET
            resolution = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            resolution,
            current_time(),
            ticket_id
        )
    )


    add_history(
        connection,
        ticket_id,
        staff["name"],
        "Resolution Added",
        resolution
    )


    connection.commit()

    connection.close()


    if wants_json_response():

        return json_success(
            "Resolution saved successfully."
        )


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# ADD INTERNAL NOTE
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/note",
    methods=["POST"]
)
def add_ticket_note(ticket_id):

    ticket, staff, connection = (
        get_ticket_for_update(ticket_id)
    )


    if not staff:

        return redirect(
            url_for("login")
        )


    if not ticket:

        return (
            "Access denied or ticket not found.",
            403
        )


    note = normalize_text(
        request.form.get("note")
    )


    if not note:

        connection.close()

        return (
            "Note cannot be empty.",
            400
        )


    add_history(
        connection,
        ticket_id,
        staff["name"],
        "Internal Note",
        note
    )


    connection.execute(
        """
        UPDATE tickets

        SET updated_at = ?

        WHERE id = ?
        """,
        (
            current_time(),
            ticket_id
        )
    )


    connection.commit()

    connection.close()


    if wants_json_response():

        return json_success(
            "Internal note added successfully."
        )


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# ADMIN ASSIGN / REASSIGN TICKET
# =========================================================

@app.route(
    "/tickets/<int:ticket_id>/assign",
    methods=["POST"]
)
def assign_ticket(ticket_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return (
            "Access denied.",
            403
        )


    assigned_to_value = normalize_text(
        request.form.get("assigned_to")
    )


    connection = get_database()


    ticket = connection.execute(
        """
        SELECT *
        FROM tickets
        WHERE id = ?
        """,
        (ticket_id,)
    ).fetchone()


    if not ticket:

        connection.close()

        return (
            "Ticket not found.",
            404
        )


    assigned_to = None


    if assigned_to_value:

        try:

            assigned_to = int(
                assigned_to_value
            )

        except ValueError:

            connection.close()

            return (
                "Invalid staff account.",
                400
            )


        assigned_staff = connection.execute(
            """
            SELECT
                id,
                name,
                role,
                active

            FROM ict_staff

            WHERE id = ?
            """,
            (assigned_to,)
        ).fetchone()


        if not assigned_staff:

            connection.close()

            return (
                "Selected staff account does not exist.",
                400
            )


        if not assigned_staff["active"]:

            connection.close()

            return (
                "Selected staff account is inactive.",
                400
            )


    if assigned_to:

        new_status = "Assigned"

    else:

        new_status = "Open"


    connection.execute(
        """
        UPDATE tickets

        SET
            assigned_to = ?,
            status = ?,
            updated_at = ?

        WHERE id = ?
        """,
        (
            assigned_to,
            new_status,
            current_time(),
            ticket_id
        )
    )


    if assigned_to:

        add_history(
            connection,
            ticket_id,
            staff["name"],
            "Ticket Assigned",
            f"Ticket assigned to {assigned_staff['name']}."
        )

    else:

        add_history(
            connection,
            ticket_id,
            staff["name"],
            "Ticket Unassigned",
            "Ticket returned to the unassigned queue."
        )


    connection.commit()

    connection.close()


    return redirect(
        url_for(
            "ticket_details",
            ticket_id=ticket_id
        )
    )


# =========================================================
# STAFF MANAGEMENT DATA
# =========================================================

def get_staff_management_data():

    connection = get_database()


    staff = connection.execute(
        """
        SELECT
            id,
            name,
            username,
            role,
            active

        FROM ict_staff

        ORDER BY
            CASE
                WHEN role = 'admin'
                THEN 0
                ELSE 1
            END,

            name ASC
        """
    ).fetchall()


    coverage = connection.execute(
        """
        SELECT
            c.id,
            c.staff_id,
            c.coverage_area,
            s.name AS staff_name,
            s.username AS staff_username

        FROM staff_coverage c

        INNER JOIN ict_staff s
            ON c.staff_id = s.id

        ORDER BY
            s.name ASC,
            c.coverage_area ASC
        """
    ).fetchall()


    sections = connection.execute(
        """
        SELECT
            id,
            name,
            active

        FROM hospital_sections

        ORDER BY
            name ASC
        """
    ).fetchall()

    availability = connection.execute(
        """
        SELECT
            absence.id,
            absence.staff_id,
            absent_staff.name AS staff_name,
            absence.coverage_area,
            absence.substitute_staff_id,
            substitute.name AS substitute_name,
            absence.start_date,
            absence.end_date,
            absence.reason,
            absence.active,
            absence.created_at
        FROM staff_absences absence
        INNER JOIN ict_staff absent_staff
            ON absent_staff.id = absence.staff_id
        LEFT JOIN ict_staff substitute
            ON substitute.id = absence.substitute_staff_id
        ORDER BY
            absence.start_date DESC,
            absence.id DESC
        """
    ).fetchall()


    connection.close()


    return (
        staff,
        coverage,
        sections,
        availability
    )


# =========================================================
# ADMIN STAFF MANAGEMENT
# =========================================================

@app.route("/admin/staff")
def admin_staff():

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return (
            "Access denied",
            403
        )


    all_staff, coverage, sections, availability_rows = (
        get_staff_management_data()
    )

    today = date.today().isoformat()
    availability = []
    for item in availability_rows:
        entry = dict(item)
        if not entry["active"]:
            entry["status"] = "Cancelled"
        elif entry["start_date"] <= today <= entry["end_date"]:
            entry["status"] = "On leave today"
        elif entry["start_date"] > today:
            entry["status"] = "Scheduled"
        else:
            entry["status"] = "Ended"
        availability.append(entry)

    technicians = [
        member
        for member in all_staff
        if member["role"] == "technician" and member["active"]
    ]

    active_section_names = {
        section["name"]
        for section in sections
        if section["active"]
    }
    technician_coverage = {}
    for item in coverage:
        if item["coverage_area"] in active_section_names:
            technician_coverage.setdefault(
                str(item["staff_id"]),
                []
            ).append(item["coverage_area"])


    return render_template(
        "staff.html",
        staff=staff,

        # IMPORTANT:
        # staff.html expects "staff_members".
        # This fixes the empty staff account list.

        staff_members=all_staff,

        coverage=coverage,
        sections=sections,
        availability=availability,
        technicians=technicians,
        technician_coverage=technician_coverage
    )


# =========================================================
# CREATE STAFF ACCOUNT
# =========================================================

@app.route(
    "/admin/staff/create",
    methods=["POST"]
)
def create_staff():

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    name = normalize_text(
        request.form.get("name")
    )

    username = normalize_text(
        request.form.get("username")
    )

    password = normalize_text(
        request.form.get("password")
    )

    role = normalize_text(
        request.form.get("role")
    )


    if not name:

        return json_error(
            "Staff name is required."
        )


    if not username:

        return json_error(
            "Username is required."
        )


    if not password:

        return json_error(
            "Password is required."
        )


    if role not in [
        "technician",
        "admin"
    ]:

        return json_error(
            "Invalid staff role."
        )


    connection = get_database()


    existing = connection.execute(
        """
        SELECT id
        FROM ict_staff
        WHERE username = ?
        """,
        (username,)
    ).fetchone()


    if existing:

        connection.close()

        return json_error(
            "That username is already in use."
        )


    cursor = connection.execute(
        """
        INSERT INTO ict_staff (
            name,
            username,
            password,
            role,
            active
        )

        VALUES (
            ?, ?, ?, ?, 1
        )
        """,
        (
            name,
            username,
            password,
            role
        )
    )


    connection.commit()

    connection.close()


    return json_success(
        "Staff account created successfully.",
        staff={
            "id": cursor.lastrowid,
            "name": name,
            "username": username,
            "role": role
        }
    )


# =========================================================
# ADD STAFF COVERAGE
# =========================================================

@app.route(
    "/admin/coverage/add",
    methods=["POST"]
)
def add_coverage():

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    staff_id_value = normalize_text(
        request.form.get("staff_id")
    )

    coverage_area = normalize_text(
        request.form.get("coverage_area")
    )


    try:

        staff_id = int(
            staff_id_value
        )

    except ValueError:

        return json_error(
            "Invalid staff account."
        )


    if not coverage_area:

        return json_error(
            "Coverage area is required."
        )


    connection = get_database()


    selected_staff = connection.execute(
        """
        SELECT
            id,
            name,
            role,
            active

        FROM ict_staff

        WHERE id = ?
        """,
        (staff_id,)
    ).fetchone()


    if not selected_staff:

        connection.close()

        return json_error(
            "Staff account not found."
        )


    if selected_staff["role"] != "technician":

        connection.close()

        return json_error(
            "Coverage can only be assigned to technicians."
        )


    section = connection.execute(
        """
        SELECT id
        FROM hospital_sections
        WHERE name = ?
          AND active = 1
        """,
        (coverage_area,)
    ).fetchone()


    if not section:

        connection.close()

        return json_error(
            "The selected hospital section is not active."
        )


    existing = connection.execute(
        """
        SELECT id
        FROM staff_coverage

        WHERE staff_id = ?
          AND coverage_area = ?
        """,
        (
            staff_id,
            coverage_area
        )
    ).fetchone()


    if existing:

        connection.close()

        return json_error(
            "This coverage assignment already exists."
        )


    cursor = connection.execute(
        """
        INSERT INTO staff_coverage (
            staff_id,
            coverage_area
        )

        VALUES (?, ?)
        """,
        (
            staff_id,
            coverage_area
        )
    )


    connection.commit()

    connection.close()


    return json_success(
        "Coverage area added successfully.",
        coverage={
            "id": cursor.lastrowid,
            "staff_id": staff_id,
            "coverage_area": coverage_area
        }
    )


# =========================================================
# DELETE COVERAGE
# =========================================================

@app.route(
    "/admin/coverage/<int:coverage_id>/delete",
    methods=["POST"]
)
def delete_coverage(coverage_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    connection = get_database()


    coverage = connection.execute(
        """
        SELECT id, staff_id, coverage_area
        FROM staff_coverage
        WHERE id = ?
        """,
        (coverage_id,)
    ).fetchone()


    if not coverage:

        connection.close()

        return json_error(
            "Coverage assignment not found.",
            404
        )

    active_absence = connection.execute(
        """
        SELECT id
        FROM staff_absences
        WHERE staff_id = ?
          AND coverage_area = ?
          AND active = 1
          AND end_date >= ?
        LIMIT 1
        """,
        (
            coverage["staff_id"],
            coverage["coverage_area"],
            date.today().isoformat()
        )
    ).fetchone()

    if active_absence:

        connection.close()

        return json_error(
            "Cancel the active absence schedule before removing this work-area coverage."
        )


    connection.execute(
        """
        DELETE FROM staff_coverage
        WHERE id = ?
        """,
        (coverage_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Coverage area removed successfully."
    )


# =========================================================
# STAFF AVAILABILITY
# =========================================================

@app.route(
    "/admin/availability/add",
    methods=["POST"]
)
def add_staff_absence():

    staff = get_current_staff()

    if not staff:
        return redirect(url_for("login"))

    if staff["role"] != "admin":
        return json_error("Access denied.", 403)

    staff_id_value = normalize_text(
        request.form.get("staff_id")
    )
    substitute_id_value = normalize_text(
        request.form.get("substitute_staff_id")
    )
    coverage_area = normalize_text(
        request.form.get("coverage_area")
    )
    start_date = normalize_text(
        request.form.get("start_date")
    )
    end_date = normalize_text(
        request.form.get("end_date")
    )
    reason = normalize_text(
        request.form.get("reason")
    )

    try:
        absent_staff_id = int(staff_id_value)
    except ValueError:
        return json_error("Select a valid staff member.")

    substitute_staff_id = None
    if substitute_id_value:
        try:
            substitute_staff_id = int(substitute_id_value)
        except ValueError:
            return json_error("Select a valid replacement technician.")

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError:
        return json_error("Enter valid start and end dates.")

    if start > end:
        return json_error("The end date cannot be before the start date.")

    if not coverage_area:
        return json_error("Select a work area for this absence.")

    connection = get_database()

    absent_staff = connection.execute(
        """
        SELECT id, name
        FROM ict_staff
        WHERE id = ?
          AND role = 'technician'
          AND active = 1
        """,
        (absent_staff_id,)
    ).fetchone()
    if not absent_staff:
        connection.close()
        return json_error("The selected technician is not active.")

    covered_area = connection.execute(
        """
        SELECT 1
        FROM staff_coverage
        WHERE staff_id = ?
          AND coverage_area = ?
        """,
        (absent_staff_id, coverage_area)
    ).fetchone()
    if not covered_area:
        connection.close()
        return json_error(
            "The selected technician is not assigned to that work area."
        )

    active_area = connection.execute(
        """
        SELECT 1
        FROM hospital_sections
        WHERE name = ?
          AND active = 1
        """,
        (coverage_area,)
    ).fetchone()
    if not active_area:
        connection.close()
        return json_error("The selected work area is not active.")

    substitute_name = None
    if substitute_staff_id is not None:
        if substitute_staff_id == absent_staff_id:
            connection.close()
            return json_error(
                "A technician cannot be their own replacement."
            )

        substitute = connection.execute(
            """
            SELECT id, name
            FROM ict_staff
            WHERE id = ?
              AND role = 'technician'
              AND active = 1
            """,
            (substitute_staff_id,)
        ).fetchone()
        if not substitute:
            connection.close()
            return json_error(
                "The selected replacement is not an active technician."
            )
        substitute_name = substitute["name"]

    overlapping_absence = connection.execute(
        """
        SELECT id
        FROM staff_absences
        WHERE staff_id = ?
          AND coverage_area = ?
          AND active = 1
          AND start_date <= ?
          AND end_date >= ?
        LIMIT 1
        """,
        (
            absent_staff_id,
            coverage_area,
            end_date,
            start_date
        )
    ).fetchone()
    if overlapping_absence:
        connection.close()
        return json_error(
            "An active absence already overlaps these dates for this work area."
        )

    cursor = connection.execute(
        """
        INSERT INTO staff_absences (
            staff_id,
            coverage_area,
            substitute_staff_id,
            start_date,
            end_date,
            reason,
            active,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (
            absent_staff_id,
            coverage_area,
            substitute_staff_id,
            start_date,
            end_date,
            reason,
            current_time()
        )
    )

    connection.commit()
    connection.close()

    today = date.today().isoformat()
    if start_date <= today <= end_date:
        status = "On leave today"
    elif start_date > today:
        status = "Scheduled"
    else:
        status = "Ended"

    return json_success(
        "Staff availability updated successfully.",
        availability={
            "id": cursor.lastrowid,
            "staff_id": absent_staff_id,
            "staff_name": absent_staff["name"],
            "coverage_area": coverage_area,
            "substitute_staff_id": substitute_staff_id,
            "substitute_name": substitute_name,
            "start_date": start_date,
            "end_date": end_date,
            "reason": reason,
            "active": True,
            "status": status
        }
    )


@app.route(
    "/admin/availability/<int:absence_id>/cancel",
    methods=["POST"]
)
def cancel_staff_absence(absence_id):

    staff = get_current_staff()

    if not staff:
        return redirect(url_for("login"))

    if staff["role"] != "admin":
        return json_error("Access denied.", 403)

    connection = get_database()
    absence = connection.execute(
        """
        SELECT id
        FROM staff_absences
        WHERE id = ?
          AND active = 1
        """,
        (absence_id,)
    ).fetchone()

    if not absence:
        connection.close()
        return json_error(
            "Active availability record not found.",
            404
        )

    connection.execute(
        """
        UPDATE staff_absences
        SET active = 0
        WHERE id = ?
        """,
        (absence_id,)
    )
    connection.commit()
    connection.close()

    return json_success(
        "Availability record cancelled. Its history has been retained.",
        availability_id=absence_id
    )


# =========================================================
# ADD HOSPITAL SECTION
# =========================================================

@app.route(
    "/admin/sections/add",
    methods=["POST"]
)
def add_section():

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    name = normalize_text(
        request.form.get("name")
    )


    if not name:

        return json_error(
            "Section name is required."
        )


    connection = get_database()


    existing = connection.execute(
        """
        SELECT id
        FROM hospital_sections
        WHERE name = ?
        """,
        (name,)
    ).fetchone()


    if existing:

        connection.close()

        return json_error(
            "That hospital section already exists."
        )


    cursor = connection.execute(
        """
        INSERT INTO hospital_sections (
            name,
            active
        )

        VALUES (?, 1)
        """,
        (name,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Hospital section added successfully.",
        section={
            "id": cursor.lastrowid,
            "name": name,
            "active": True
        }
    )


# =========================================================
# EDIT HOSPITAL SECTION
# =========================================================

@app.route(
    "/admin/sections/<int:section_id>/edit",
    methods=["POST"]
)
def edit_section(section_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    new_name = normalize_text(
        request.form.get("name")
    )


    if not new_name:

        return json_error(
            "Section name is required."
        )


    connection = get_database()


    section = connection.execute(
        """
        SELECT
            id,
            name

        FROM hospital_sections

        WHERE id = ?
        """,
        (section_id,)
    ).fetchone()


    if not section:

        connection.close()

        return json_error(
            "Hospital section not found.",
            404
        )


    old_name = section["name"]


    duplicate = connection.execute(
        """
        SELECT id
        FROM hospital_sections

        WHERE name = ?
          AND id != ?
        """,
        (
            new_name,
            section_id
        )
    ).fetchone()


    if duplicate:

        connection.close()

        return json_error(
            "Another section already uses that name."
        )


    connection.execute(
        """
        UPDATE hospital_sections

        SET name = ?

        WHERE id = ?
        """,
        (
            new_name,
            section_id
        )
    )


    # Keep existing coverage assignments
    # synchronized with the renamed section.

    connection.execute(
        """
        UPDATE staff_coverage

        SET coverage_area = ?

        WHERE coverage_area = ?
        """,
        (
            new_name,
            old_name
        )
    )

    connection.execute(
        """
        UPDATE staff_absences
        SET coverage_area = ?
        WHERE coverage_area = ?
        """,
        (
            new_name,
            old_name
        )
    )


    connection.commit()

    connection.close()


    return json_success(
        "Hospital section updated successfully."
    )


# =========================================================
# DEACTIVATE HOSPITAL SECTION
# =========================================================

@app.route(
    "/admin/sections/<int:section_id>/deactivate",
    methods=["POST"]
)
def deactivate_section(section_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    connection = get_database()


    section = connection.execute(
        """
        SELECT
            id,
            name

        FROM hospital_sections

        WHERE id = ?
        """,
        (section_id,)
    ).fetchone()


    if not section:

        connection.close()

        return json_error(
            "Hospital section not found.",
            404
        )


    connection.execute(
        """
        UPDATE hospital_sections

        SET active = 0

        WHERE id = ?
        """,
        (section_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Hospital section deactivated successfully."
    )


# =========================================================
# ACTIVATE HOSPITAL SECTION
# =========================================================

@app.route(
    "/admin/sections/<int:section_id>/activate",
    methods=["POST"]
)
def activate_section(section_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    connection = get_database()


    section = connection.execute(
        """
        SELECT id
        FROM hospital_sections
        WHERE id = ?
        """,
        (section_id,)
    ).fetchone()


    if not section:

        connection.close()

        return json_error(
            "Hospital section not found.",
            404
        )


    connection.execute(
        """
        UPDATE hospital_sections

        SET active = 1

        WHERE id = ?
        """,
        (section_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Hospital section activated successfully."
    )


# =========================================================
# DELETE HOSPITAL SECTION
# =========================================================

@app.route(
    "/admin/sections/<int:section_id>/delete",
    methods=["POST"]
)
def delete_section(section_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    connection = get_database()


    section = connection.execute(
        """
        SELECT
            id,
            name

        FROM hospital_sections

        WHERE id = ?
        """,
        (section_id,)
    ).fetchone()


    if not section:

        connection.close()

        return json_error(
            "Hospital section not found.",
            404
        )


    # -----------------------------------------------------
    # DO NOT DELETE A SECTION THAT HAS TICKETS
    # -----------------------------------------------------

    ticket_using_section = connection.execute(
        """
        SELECT id
        FROM tickets

        WHERE department = ?

        LIMIT 1
        """,
        (section["name"],)
    ).fetchone()


    if ticket_using_section:

        connection.close()

        return json_error(
            "This section cannot be deleted because tickets already reference it. Deactivate it instead."
        )

    availability_using_section = connection.execute(
        """
        SELECT id
        FROM staff_absences
        WHERE coverage_area = ?
        LIMIT 1
        """,
        (section["name"],)
    ).fetchone()

    if availability_using_section:

        connection.close()

        return json_error(
            "This section is referenced by staff availability history. Deactivate it instead."
        )


    # -----------------------------------------------------
    # REMOVE COVERAGE REFERENCES
    # -----------------------------------------------------

    connection.execute(
        """
        DELETE FROM staff_coverage

        WHERE coverage_area = ?
        """,
        (section["name"],)
    )


    connection.execute(
        """
        DELETE FROM hospital_sections

        WHERE id = ?
        """,
        (section_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Hospital section deleted successfully."
    )


# =========================================================
# DEACTIVATE STAFF ACCOUNT
# =========================================================

@app.route(
    "/admin/staff/<int:staff_id>/deactivate",
    methods=["POST"]
)
def deactivate_staff(staff_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    if staff_id == staff["id"]:

        return json_error(
            "You cannot deactivate your own account."
        )


    connection = get_database()


    selected_staff = connection.execute(
        """
        SELECT
            id,
            name,
            role,
            active

        FROM ict_staff

        WHERE id = ?
        """,
        (staff_id,)
    ).fetchone()


    if not selected_staff:

        connection.close()

        return json_error(
            "Staff account not found.",
            404
        )


    # -----------------------------------------------------
    # PROTECT STAFF WITH ACTIVE TICKETS
    # -----------------------------------------------------

    active_tickets = connection.execute(
        """
        SELECT COUNT(*)

        FROM tickets

        WHERE assigned_to = ?

          AND status IN (
              'Open',
              'Assigned',
              'In Progress'
          )
        """,
        (staff_id,)
    ).fetchone()[0]


    if active_tickets > 0:

        connection.close()

        return json_error(
            "This staff member has active tickets. Reassign or resolve them before deactivating the account."
        )


    # -----------------------------------------------------
    # PROTECT LAST ACTIVE ADMIN
    # -----------------------------------------------------

    if selected_staff["role"] == "admin":

        active_admins = connection.execute(
            """
            SELECT COUNT(*)

            FROM ict_staff

            WHERE role = 'admin'
              AND active = 1
            """
        ).fetchone()[0]


        if active_admins <= 1:

            connection.close()

            return json_error(
                "The last active administrator cannot be deactivated."
            )


    connection.execute(
        """
        UPDATE ict_staff

        SET active = 0

        WHERE id = ?
        """,
        (staff_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Staff account deactivated successfully."
    )


# =========================================================
# ACTIVATE STAFF ACCOUNT
# =========================================================

@app.route(
    "/admin/staff/<int:staff_id>/activate",
    methods=["POST"]
)
def activate_staff(staff_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    connection = get_database()


    selected_staff = connection.execute(
        """
        SELECT id
        FROM ict_staff

        WHERE id = ?
        """,
        (staff_id,)
    ).fetchone()


    if not selected_staff:

        connection.close()

        return json_error(
            "Staff account not found.",
            404
        )


    connection.execute(
        """
        UPDATE ict_staff

        SET active = 1

        WHERE id = ?
        """,
        (staff_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Staff account activated successfully."
    )


# =========================================================
# DELETE STAFF ACCOUNT
# =========================================================

@app.route(
    "/admin/staff/<int:staff_id>/delete",
    methods=["POST"]
)
def delete_staff(staff_id):

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return json_error(
            "Access denied.",
            403
        )


    if staff_id == staff["id"]:

        return json_error(
            "You cannot delete your own account."
        )


    connection = get_database()


    selected_staff = connection.execute(
        """
        SELECT
            id,
            name,
            role,
            active

        FROM ict_staff

        WHERE id = ?
        """,
        (staff_id,)
    ).fetchone()


    if not selected_staff:

        connection.close()

        return json_error(
            "Staff account not found.",
            404
        )


    # -----------------------------------------------------
    # PROTECT ACTIVE TICKETS
    # -----------------------------------------------------

    active_tickets = connection.execute(
        """
        SELECT COUNT(*)

        FROM tickets

        WHERE assigned_to = ?

          AND status IN (
              'Open',
              'Assigned',
              'In Progress'
          )
        """,
        (staff_id,)
    ).fetchone()[0]


    if active_tickets > 0:

        connection.close()

        return json_error(
            "This staff member has active tickets. Reassign or resolve them before deleting the account."
        )

    availability_records = connection.execute(
        """
        SELECT id
        FROM staff_absences
        WHERE staff_id = ?
           OR substitute_staff_id = ?
        LIMIT 1
        """,
        (staff_id, staff_id)
    ).fetchone()

    if availability_records:

        connection.close()

        return json_error(
            "This staff member appears in availability history. Deactivate the account to retain those records."
        )


    # -----------------------------------------------------
    # PROTECT LAST ACTIVE ADMIN
    # -----------------------------------------------------

    if selected_staff["role"] == "admin":

        active_admins = connection.execute(
            """
            SELECT COUNT(*)

            FROM ict_staff

            WHERE role = 'admin'
              AND active = 1
            """
        ).fetchone()[0]


        if active_admins <= 1:

            connection.close()

            return json_error(
                "The last active administrator cannot be deleted."
            )


    # -----------------------------------------------------
    # PRESERVE HISTORICAL TICKETS
    # -----------------------------------------------------
    # Instead of deleting historical ticket records,
    # remove their staff assignment.

    connection.execute(
        """
        UPDATE tickets

        SET assigned_to = NULL

        WHERE assigned_to = ?
        """,
        (staff_id,)
    )


    # -----------------------------------------------------
    # DELETE COVERAGE
    # -----------------------------------------------------

    connection.execute(
        """
        DELETE FROM staff_coverage

        WHERE staff_id = ?
        """,
        (staff_id,)
    )


    # -----------------------------------------------------
    # DELETE STAFF ACCOUNT
    # -----------------------------------------------------

    connection.execute(
        """
        DELETE FROM ict_staff

        WHERE id = ?
        """,
        (staff_id,)
    )


    connection.commit()

    connection.close()


    return json_success(
        "Staff account deleted successfully."
    )


# =========================================================
# ADMIN HOME
# =========================================================

@app.route("/admin")
def admin_home():

    staff = get_current_staff()


    if not staff:

        return redirect(
            url_for("login")
        )


    if staff["role"] != "admin":

        return redirect(
            url_for("dashboard")
        )


    return redirect(
        url_for("admin_staff")
    )


# =========================================================
# APPLICATION START
# =========================================================

if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )