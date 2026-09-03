# IT Help Desk System

A web-based IT Help Desk and Ticketing System designed to help organizations record, manage, track, and resolve technical support requests.

## Project Overview

The IT Help Desk System provides a simple platform where users can submit IT support tickets and technicians can manage those tickets from a protected dashboard.

The system demonstrates practical skills in web development, database management, user authentication, input validation, and IT support workflow management.

## Features

- User ticket submission
- Automatic ticket numbering
- Ticket confirmation after submission
- Technician login
- Protected technician dashboard
- Ticket statistics
- Ticket search
- Ticket details view
- Ticket priority management
- Ticket status management
- Resolution recording
- Automatic resolution status when a resolution is submitted
- Form validation
- Responsive user interface
- SQLite database storage

## Ticket Workflow

The system supports the following ticket workflow:

1. User submits an IT support request.
2. The system generates a unique ticket number.
3. The ticket is initially assigned an Open status.
4. A technician reviews the ticket.
5. The technician can change the status to In Progress.
6. The technician investigates and records the resolution.
7. When a resolution is saved, the ticket is automatically marked as Resolved.
8. The dashboard statistics are updated automatically.

## Technologies Used

- Python
- Flask
- SQLite
- HTML5
- CSS3
- Jinja2

## Project Structure

```text
IT-helpdesk-system/
│
├── app.py
├── database.py
├── requirements.txt
├── README.md
├── .gitignore
│
└── templates/
    ├── index.html
    ├── dashboard.html
    ├── ticket.html
    ├── login.html
    └── success.html