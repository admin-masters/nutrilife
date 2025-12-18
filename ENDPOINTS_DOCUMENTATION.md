# Nutrilift API Endpoints Documentation

Complete list of all URL endpoints in the Nutrilift project with descriptions.

---

## Root/Main URLs (`backend/nutrilift/urls.py`)

### `/health/`
**Method:** GET  
**Description:** Health check endpoint that returns `{"ok": True}` to verify the API is running.

### `/admin/` (or configured `ADMIN_URL`)
**Method:** GET, POST  
**Description:** Django admin interface for managing all application data. Requires admin/staff access.

### `/whoami/`
**Method:** GET  
**Authentication:** Requires SAPA_ADMIN, ORG_ADMIN role, or superuser  
**Description:** Returns current user information including email, roles, and active organization.

---

## Screening Module (`/screening/`)

### `/screening/teacher/<token>/`
**Method:** GET  
**Authentication:** Public (token-based, no login required)  
**Description:** Public teacher portal entry point using organization screening link token. Resolves organization by token, starts a public teacher session, and displays the teacher portal dashboard. Token format: `<org-slug>-<8-char-random>`.

### `/screening/teacher/`
**Method:** GET  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Teacher portal dashboard showing list of students with filtering by classroom, risk level (GREEN/AMBER/RED), and search functionality. Displays students with their last screening risk level.

### `/screening/teacher/<token>/add-student/`
**Method:** GET, POST  
**Authentication:** Public (token-based, no login required)  
**Description:** Public token-based form to add a new student and create their initial screening. Uses organization token to identify the school. Auto-generates student code, creates guardian if needed, and sends WhatsApp message after screening.

### `/screening/teacher/add-student/`
**Method:** GET, POST  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Form to add a new student and create their initial screening in one step. Auto-generates student code, creates guardian if needed, and sends WhatsApp message after screening. (Legacy non-token route kept for backward compatibility)

### `/screening/teacher/screen/<int:student_id>/`
**Method:** GET, POST  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Create a new nutritional screening for a specific student. Accepts height, weight, age, gender, and questionnaire answers. Computes risk level and automatically sends WhatsApp education or assistance message based on risk and income status.

### `/screening/teacher/result/<int:screening_id>/`
**Method:** GET  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Display screening results page showing risk level, red flags, and last message sent status for a completed screening.

### `/screening/admin/export/screenings.csv`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN, INDITECH role, or superuser  
**Description:** Export screenings data as CSV file for the last 6 months (or custom date range via `?since=YYYY-MM-DD`). Includes student details, measurements, risk levels, and red flags.

### `/screening/send/education/<int:screening_id>/`
**Method:** GET, POST  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Manually trigger sending educational WhatsApp message to parent/guardian for a specific screening. Redirects back to screening result page.

### `/screening/send/assistance/<int:screening_id>/`
**Method:** GET, POST  
**Authentication:** Requires TEACHER, ORG_ADMIN role, or superuser  
**Description:** Manually trigger sending assistance invitation WhatsApp message to parent/guardian for a specific screening. Only works for low-income students. Redirects back to screening result page.

---

## Messaging Module

### `/webhooks/whatsapp/`
**Method:** GET, POST  
**CSRF:** Exempt  
**Description:** WhatsApp webhook endpoint for Meta Cloud API. GET method handles webhook verification during Meta setup. POST method receives message status updates (sent, delivered, read, failed) and updates MessageLog records accordingly.

### `/whatsapp/preview/<int:log_id>/`
**Method:** GET  
**Authentication:** None required (but typically accessed from authenticated contexts)  
**Description:** Preview page for WhatsApp messages that shows the pre-filled message content and provides a click-to-open WhatsApp link. Does not send messages automatically. Supports optional `?next=<url>` query parameter to redirect after preview. Works with RED_EDU_V1 and RED_ASSIST_V1 template codes.

---

## Assistance Module (`/assist/`)

### `/assist/apply`
**Method:** GET, POST  
**Authentication:** Public (no authentication required)  
**Description:** Public application form for parents/guardians to apply for nutritional assistance. Accessed via WhatsApp link with parameters: `?student_id=&screening_id=&lang=`. Creates Application record with APPLIED status.

### `/assist/thanks`
**Method:** GET  
**Authentication:** Public  
**Description:** Thank you/confirmation page displayed after parent submits assistance application form.

### `/assist/admin`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** School admin dashboard showing assistance applications filtered by status (APPLIED/FORWARDED). Displays summary metrics including screening counts, red flag counts by gender, and application statistics for configurable time periods (3m, 6m, 12m, 18m, all).

### `/assist/admin/forward-all`
**Method:** POST  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Bulk action to forward all APPLIED applications to SAPA (change status to FORWARDED) for the organization. Updates forwarding timestamp and user.

### `/assist/admin/forward/<int:app_id>`
**Method:** POST  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Forward a single assistance application to SAPA by changing its status from APPLIED to FORWARDED. Updates forwarding timestamp and user.

### `/assist/admin/applications`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Applications listing page showing all assistance applications filtered by status (APPLIED/FORWARDED). Displays application details including student information, guardian contacts, and application timestamps. Supports `?status=APPLIED` or `?status=FORWARDED` query parameters.

### `/assist/admin/metrics/students/<slug:metric>`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Student metrics listing page showing filtered students based on metric type. Supported metrics: `all` (total students), `screened`, `redflag`, `boys_screened`, `boys_redflag`, `girls_screened`, `girls_redflag`. Supports `?period=3m|6m|12m|18m|all` query parameter for time filtering. Shows student name, class, age, phone, and screening status in a paginated list.

### `/assist/admin/metrics/applications/<slug:status>`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Application metrics listing page showing applications filtered by status. Supported statuses: `pending` (FORWARDED applications), `approved` (APPROVED applications). Supports `?period=3m|6m|12m|18m|all` query parameter for time filtering based on forwarding/approval dates. Displays application details with student information and approval timestamps.

### `/assist/sapa/approvals`
**Method:** GET  
**Authentication:** Requires SAPA_ADMIN role or superuser  
**Description:** SAPA admin dashboard showing all schools with counts of forwarded and approved applications. Allows selecting a school to view pending applications awaiting approval.

### `/assist/sapa/approve-all`
**Method:** POST  
**Authentication:** Requires SAPA_ADMIN role or superuser  
**Description:** Bulk approve all FORWARDED applications for a specific school (requires `school_id` in POST data). Changes status to APPROVED.

### `/assist/sapa/approve-top-n`
**Method:** POST  
**Authentication:** Requires SAPA_ADMIN role or superuser  
**Description:** Approve top N applications for a school (requires `school_id` and `n` in POST data). Approves applications in priority order and returns count of approved vs skipped.

### `/assist/sapa/reject-all`
**Method:** POST  
**Authentication:** Requires SAPA_ADMIN role or superuser  
**Description:** Bulk reject all FORWARDED applications for a specific school (requires `school_id` in POST data). Changes status to REJECTED.

---

## Program Module (`/program/`)

### `/qr/<str:token>/`
**Method:** GET  
**Authentication:** Public (no authentication required)  
**Description:** Public landing page displayed after scanning a monthly supply pack QR code. Shows student information and instructions. Records QR scan audit log.

### `/program/compliance/start`
**Method:** GET  
**Authentication:** Public  
**Description:** Backward-compatibility redirect endpoint. Accepts `?token=<qr_token>` and redirects to the compliance form URL.

### `/program/compliance/<str:token>`
**Method:** GET, POST  
**Authentication:** Public  
**Description:** Day-27 compliance form for parents to submit compliance status after receiving monthly nutritional supply. Accepts compliance status and optional notes. Applies gating rules after submission.

### `/program/compliance/<str:token>/thanks`
**Method:** GET  
**Authentication:** Public  
**Description:** Success confirmation page displayed after parent submits compliance form.

### `/program/fulfillment/mark-delivered/<int:supply_id>/`
**Method:** POST  
**Authentication:** Requires ORG_ADMIN, SAPA_ADMIN, INDITECH role, or superuser  
**Description:** Mark a monthly supply as delivered. Checks for school suspension due to overdue screening milestones. Redirects to admin change page after marking.

### `/program/milestones`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Organization admin dashboard for screening milestones. Shows due (within 14 days), overdue, and completed milestones. Displays school suspension status and reason if applicable.

### `/program/sapa/milestones`
**Method:** GET  
**Authentication:** Requires SAPA_ADMIN role or superuser  
**Description:** SAPA admin overview of screening milestones across all schools. Shows aggregated counts (overdue, due, completed) per organization in a summary table.

---

## Reporting Module (`/reporting/`)

### `/reporting/school`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** School-level reporting dashboard showing 6-month summary statistics including screening counts, enrollment metrics, and daily trend data. Displays report submission status and next due date.

### `/reporting/school/export.csv`
**Method:** GET  
**Authentication:** Requires ORG_ADMIN role or superuser  
**Description:** Export school reporting data as CSV. Supports custom date range via `?start=YYYY-MM-DD&end=YYYY-MM-DD` query parameters. Defaults to last 6 months.

### `/reporting/inditech`
**Method:** GET  
**Authentication:** Requires INDITECH role or superuser  
**Description:** Inditech dashboard showing aggregated statistics across all schools for the last 6 months. Displays summary data per organization including next report due dates.

### `/reporting/inditech/school/<int:org_id>`
**Method:** GET  
**Authentication:** Requires INDITECH role or superuser  
**Description:** Detailed view of reporting data for a specific school/organization. Shows 6-month summary and 30-day trend visualization.

### `/reporting/inditech/school/<int:org_id>/export.csv`
**Method:** GET  
**Authentication:** Requires INDITECH role or superuser  
**Description:** Export reporting data for a specific school as CSV file. Includes 6-month period summary metrics.

### `/inditech/`
**Method:** GET  
**Authentication:** Requires staff access (is_staff=True)  
**Description:** Simple Inditech console endpoint. Returns 200 OK for staff users, 403 for others.

---

## Operations Module (`/ops/`)

### `/ops/healthz`
**Method:** GET  
**Authentication:** None required  
**Description:** Advanced health check endpoint that verifies both API and Celery beat service status. Returns `{"ok": True, "celery_beat_ok": true/false}`. Checks if Celery beat last heartbeat was within 3 minutes.

---

## Organizations Module (`/orgs/`)

### `/orgs/start`
**Method:** GET, POST  
**Authentication:** Public (no authentication required)  
**Description:** Organization signup and login page with two modes. Default mode is "signup" which creates a new organization with admin user account. Mode "login" (via `?mode=login`) allows existing users to authenticate. On successful signup or login, redirects to the assistance admin dashboard. Auto-generates unique screening link token for new organizations.

---

## Notes

- Most endpoints require organization context to be set (via middleware)
- Role-based access control (RBAC) is enforced using `@require_roles` decorator
- Many endpoints support filtering via query parameters
- CSV exports default to 6-month periods but support custom date ranges
- Public endpoints (QR codes, compliance forms, application forms, token-based teacher portal) use token-based access
- WhatsApp integration uses webhook for status updates
- All actions are logged via audit system
- Token-based teacher portal routes allow public access without authentication using organization screening link tokens
- Metric endpoints support pagination (50 items per page by default)

