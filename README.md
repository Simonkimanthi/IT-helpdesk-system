# ICT Service Desk

A web-based IT service desk for submitting, assigning, tracking, and resolving technical support requests across an organization.

## Project Overview

The ICT Service Desk gives staff a clear support-request form and gives technicians and administrators a protected workspace to manage the request lifecycle.

The system includes a responsive interface, an original locally served SVG identity, and a shared visual theme that works without remote images or font services.

## Features

- User ticket submission
- Automatic ticket numbering
- Ticket confirmation after submission
- Technician login
- Protected technician dashboard
- Ticket statistics
- Ticket search
- Daily request dashboard with date filters and access to all ticket history
- Ticket details view
- Ticket priority management
- Ticket status management
- Resolution recording
- Automatic resolution status when a resolution is submitted
- Individual staff accounts with work-area-based ticket visibility
- Automatic routing to available technicians assigned to the selected work area
- Admin-managed absences and temporary work-area cover
- Form validation
- Responsive user interface
- SQLite database storage

## Ticket Workflow

The system supports the following ticket workflow:

1. User submits an IT support request.
2. The system generates a unique ticket number.
3. The system assigns the ticket to an available technician covering the
   selected work area, or leaves it Open if no eligible technician is available.
4. The assigned technician reviews the ticket.
5. The technician can change the status to In Progress.
6. The technician investigates and records the resolution.
7. When a resolution is saved, the ticket is automatically marked as Resolved.
8. The dashboard statistics are updated automatically.

Ticket history is retained. The dashboard opens on today's requests and also
supports yesterday, the last seven days, this month, and all history. Admins can
record a technician's absence for a date range and choose a temporary
replacement for each affected work area. New requests during that range are
routed to the selected replacement; if no replacement is selected, routing
chooses another available technician assigned to that work area. Existing
tickets are not deleted or silently reassigned.

## Technologies Used

- Python
- Flask
- SQLite
- HTML5
- CSS3
- Jinja2

## Run Locally

1. Install the packages listed in `requirements.txt`.
2. Initialize or safely upgrade the local SQLite database with `python database.py`.
   Running this command on an existing database adds the availability schedule
   table without deleting ticket or ticket-history records.
3. Start the application with `python app.py` and open `http://127.0.0.1:5000`.

The database setup preserves existing ticket and history records while adding any fields required by the current application.

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
├── Templates/
│   ├── index.html
│   ├── dashboard.html
│   ├── ticket.html
│   ├── login.html
│   ├── success.html
│   └── staff.html
│
├── static/
│   ├── css/
│   │   └── theme.css
│   └── img/
│       └── it-support-mark.svg