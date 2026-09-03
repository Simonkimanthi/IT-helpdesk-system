from flask import Flask, render_template, request, redirect, session
import sqlite3
import re

app = Flask(__name__)

app.secret_key = "helpdesk-secret-key"


# -----------------------------
# Database connection
# -----------------------------

def get_database():
    connection = sqlite3.connect("helpdesk.db")
    connection.row_factory = sqlite3.Row
    return connection


# -----------------------------
# Home / Ticket submission
# -----------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/create-ticket", methods=["POST"])
def create_ticket():

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    subject = request.form.get("subject", "").strip()
    description = request.form.get("description", "").strip()
    priority = request.form.get("priority", "").strip()

    errors = []

    # Validate name
    if not name:
        errors.append("Name is required.")
    elif len(name) < 2:
        errors.append("Name must contain at least 2 characters.")
    elif len(name) > 100:
        errors.append("Name cannot exceed 100 characters.")

    # Validate email
    email_pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

    if not email:
        errors.append("Email address is required.")
    elif not re.match(email_pattern, email):
        errors.append("Please enter a valid email address.")

    # Validate subject
    if not subject:
        errors.append("Subject is required.")
    elif len(subject) < 3:
        errors.append("Subject must contain at least 3 characters.")
    elif len(subject) > 150:
        errors.append("Subject cannot exceed 150 characters.")

    # Validate description
    if not description:
        errors.append("Problem description is required.")
    elif len(description) < 10:
        errors.append("Problem description must contain at least 10 characters.")
    elif len(description) > 5000:
        errors.append("Problem description cannot exceed 5000 characters.")

    # Validate priority
    allowed_priorities = ["Low", "Medium", "High", "Critical"]

    if priority not in allowed_priorities:
        errors.append("Invalid priority selected.")

    # If validation fails
    if errors:
        return render_template(
            "index.html",
            errors=errors,
            form=request.form
        ), 400

    connection = get_database()

    cursor = connection.execute(
        """
        INSERT INTO tickets
        (name, email, subject, description, priority)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, email, subject, description, priority)
    )

    ticket_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return render_template(
        "success.html",
        ticket_id=ticket_id
    )


# -----------------------------
# Technician login
# -----------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if username == "admin" and password == "admin123":

            session["logged_in"] = True

            return redirect("/dashboard")

        return render_template(
            "login.html",
            error="Invalid username or password."
        )

    return render_template("login.html")


# -----------------------------
# Logout
# -----------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# -----------------------------
# Technician dashboard
# -----------------------------

@app.route("/dashboard")
def dashboard():

    if not session.get("logged_in"):
        return redirect("/login")

    search = request.args.get("search", "").strip()

    connection = get_database()

    if search:

        search_value = f"%{search}%"

        tickets = connection.execute(
            """
            SELECT * FROM tickets
            WHERE CAST(id AS TEXT) LIKE ?
               OR name LIKE ?
               OR email LIKE ?
               OR subject LIKE ?
               OR status LIKE ?
               OR priority LIKE ?
            ORDER BY id DESC
            """,
            (
                search_value,
                search_value,
                search_value,
                search_value,
                search_value,
                search_value
            )
        ).fetchall()

    else:

        tickets = connection.execute(
            "SELECT * FROM tickets ORDER BY id DESC"
        ).fetchall()

    total_tickets = connection.execute(
        "SELECT COUNT(*) FROM tickets"
    ).fetchone()[0]

    open_tickets = connection.execute(
        "SELECT COUNT(*) FROM tickets WHERE status = 'Open'"
    ).fetchone()[0]

    in_progress_tickets = connection.execute(
        "SELECT COUNT(*) FROM tickets WHERE status = 'In Progress'"
    ).fetchone()[0]

    resolved_tickets = connection.execute(
        "SELECT COUNT(*) FROM tickets WHERE status = 'Resolved'"
    ).fetchone()[0]

    connection.close()

    return render_template(
        "dashboard.html",
        tickets=tickets,
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        in_progress_tickets=in_progress_tickets,
        resolved_tickets=resolved_tickets,
        search=search
    )


# -----------------------------
# Ticket details
# -----------------------------

@app.route("/ticket/<int:ticket_id>")
def ticket_details(ticket_id):

    if not session.get("logged_in"):
        return redirect("/login")

    connection = get_database()

    ticket = connection.execute(
        "SELECT * FROM tickets WHERE id = ?",
        (ticket_id,)
    ).fetchone()

    connection.close()

    if ticket is None:
        return "Ticket not found", 404

    return render_template(
        "ticket.html",
        ticket=ticket
    )


# -----------------------------
# Update ticket status
# -----------------------------

@app.route("/update-status/<int:ticket_id>", methods=["POST"])
def update_status(ticket_id):

    if not session.get("logged_in"):
        return redirect("/login")

    status = request.form.get("status", "").strip()

    allowed_statuses = [
        "Open",
        "In Progress",
        "Resolved"
    ]

    if status not in allowed_statuses:
        return "Invalid ticket status.", 400

    connection = get_database()

    ticket = connection.execute(
        "SELECT id FROM tickets WHERE id = ?",
        (ticket_id,)
    ).fetchone()

    if ticket is None:
        connection.close()
        return "Ticket not found", 404

    connection.execute(
        "UPDATE tickets SET status = ? WHERE id = ?",
        (status, ticket_id)
    )

    connection.commit()
    connection.close()

    return redirect(f"/ticket/{ticket_id}")


# -----------------------------
# Update ticket resolution
# -----------------------------

@app.route("/update-resolution/<int:ticket_id>", methods=["POST"])
def update_resolution(ticket_id):

    if not session.get("logged_in"):
        return redirect("/login")

    resolution = request.form.get("resolution", "").strip()

    if len(resolution) > 5000:
        return "Resolution cannot exceed 5000 characters.", 400

    connection = get_database()

    ticket = connection.execute(
        "SELECT id FROM tickets WHERE id = ?",
        (ticket_id,)
    ).fetchone()

    if ticket is None:
        connection.close()
        return "Ticket not found", 404

    # Save the resolution
    # If a resolution has been entered, automatically mark
    # the ticket as resolved.
    if resolution:

        connection.execute(
            """
            UPDATE tickets
            SET resolution = ?, status = 'Resolved'
            WHERE id = ?
            """,
            (resolution, ticket_id)
        )

    else:

        connection.execute(
            """
            UPDATE tickets
            SET resolution = ?
            WHERE id = ?
            """,
            (resolution, ticket_id)
        )

    connection.commit()
    connection.close()

    return redirect(f"/ticket/{ticket_id}")


# -----------------------------
# Start application
# -----------------------------

if __name__ == "__main__":
    app.run(debug=True)