# WesdomeTS — Development Progress Report
**Date:** June 12, 2026  
**Developer:** Pamela Anang  
**Project:** Wesdome Gold Mines Limited — Eagle River Mine Timesheet Management System  

---

## Project Overview

WesdomeTS is an internal web application for Wesdome Gold Mines to replace paper-based or spreadsheet timesheet tracking. Employees log their work entries, supervisors approve them, and payroll accesses completed timesheets for processing. The system enforces an approval chain based on org structure — not hardcoded department rules.

### Why we built it this way
The core principle is **vertical slice development**: complete one use case end-to-end before building peripheral features around it. This avoids building UI for features whose backend logic doesn't exist yet, and keeps the app always in a "something works" state.

---

## The Use Cases

| # | Use Case | Actor | Status |
|---|---|---|---|
| UC1 | SysAdmin creates a user and sends temp password | SysAdmin | Complete |
| UC2 | Employee logs in for the first time and resets password | Employee | Complete |
| UC3 | Employee creates a timesheet and adds entries | Employee | Complete |
| UC4 | Employee submits → Supervisor approves → Employee sees result | Employee + Supervisor | **In Progress** |
| UC5 | Payroll views completed timesheets | Payroll | Not started |
| UC6 | Employee views their approved/rejected history | Employee | Deferred (after UC4) |

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Backend | Django 5.2 | Mature, batteries-included — ORM, auth, forms, admin all built-in |
| Database | MySQL | Production-grade relational DB matching the mine's existing infrastructure |
| Frontend | TailwindCSS v4 | Utility-first, no bloat, fast to prototype with |
| Auth | Custom `AbstractBaseUser` | Off-the-shelf Django auth doesn't match the mine's employee ID + role structure |
| Env config | python-dotenv | Keeps DB credentials and secrets out of source code |
| CSS build | `@tailwindcss/cli` via npm | TailwindCSS v4 dropped the PostCSS plugin — CLI is the correct tooling |

### Access Level System
Resolved via a three-table FK chain: `User → Role → AccessLevel`

| Level | Role |
|---|---|
| 1 | SysAdmin |
| 2 | Superintendent |
| 3 | Supervisor |
| 4 | Mine Captain |
| 5 | Shifter |
| 6 | Employee |
| 7 | Payroll |

**Why this structure?** The `supervisorid` self-referential FK on `User` drives all approval routing. A supervisor approves timesheets for everyone where `supervisorid = them` — regardless of department. This mirrors real org structure and means no hardcoded department-level rules that break when people move teams.

---

## Build Journey

### Phase 1 — Project Foundation
**What we did:**
- Initialised Django project (`WesdomeTS`) and apps (`users`, `timesheets`)
- Configured MySQL connection via `.env` and `python-dotenv`
- Set up TailwindCSS v4 with the CLI (`npm run css:watch` / `npm run css:build`)
- Created `base.html` with nav, sidebar, and block structure

**Why:** Get the skeleton right first — DB connection, static file pipeline, and base template — so every subsequent feature builds on a stable foundation.

---

### Phase 2 — Custom Auth & User Management (UC1 + UC2)
**What we did:**
- Built a custom `User` model extending `AbstractBaseUser` with fields: `employeeid`, `phonenumber`, `firstname`, `lastname`, `roleid` (FK), `supervisorid` (self-referential FK), `is_temporary`, `lastresetdate`
- Added `access_level` property on `User` that traverses `User → Role → AccessLevel`
- Built `login_view` using `UserLoginForm` (Django's `AuthenticationForm`)
- Built `generate_password` — SysAdmin generates an 8-char random temp password, sets `is_temporary = True`, prints an SMS stub (Twilio pending)
- Built `password_reset_view` — forces password change on first login if `is_temporary`, clears flag after reset
- Built `user_list_view` — SysAdmin-only view of all employees grouped by department using `select_related`

**Why:** The entire approval chain depends on knowing *who* someone is and *who they report to*. Getting auth and user structure right before building any timesheet logic was non-negotiable. The `is_temporary` flag enforces the security requirement that no one uses a system-generated password beyond their first login.

**Key decisions:**
- `@login_required(login_url='login')` on every protected view — without `login_url`, Django defaults to `/accounts/login/` which doesn't exist in this project
- After login, redirect to `'profile'` not `'home'` — profile is the meaningful landing page; `home` was a duplicate route that caused a URL naming conflict (fixed by removing it)

---

### Phase 3 — Profile Page
**What we did:**
- Built `profile` view passing `draft_count`, `pending_count`, `approved_count`, `rejected_count` from the DB
- Built `profile.html` with a two-column info card and dashboard stats section
- Fixed right-column alignment — labels `font-bold`, values `text-left pl-7 justify-start`

**Why:** Every user needs a landing page that gives them immediate context — what have I submitted, what's pending. This is also the page that will eventually show role-specific dashboards (deferred).

---

### Phase 4 — Timesheet Creation (UC3)
**What we did:**
- Built `new_timesheet` view with draft protection logic:
  - If an existing Draft header exists → redirect to it (no duplicates)
  - If not → create a new header and redirect to the entry form
  - Stale drafts older than 60 days are auto-deleted on entry
- Built `add_entry` view handling all operations via a single `action` POST field:
  - `save_entry` — create or update a `MainEntry` line
  - `update_crew` — assign crew to the header
  - `delete_entry` — remove an entry
  - `submit_timesheet` — lock the header (`overallstatus = 'Submitted'`), flip all entries to `linestatus = 'New'`
- Built `add_entry.html` with an entry form, live entry table, crew selector, and submit button

**Why the `action` field pattern?** Django forms POST to a URL, not a specific function. Rather than creating separate URLs for save/delete/submit, a single view reads the `action` field and branches accordingly. This is a clean, maintainable pattern — the same view that renders the page also handles all mutations on it.

**Why lock on submit?** Once a timesheet enters the approval chain, allowing edits would invalidate decisions already made by the supervisor. Locking is industry-standard practice for any approval workflow (payroll, finance, HR).

**Why 60-day stale draft cleanup?** Without it, employees who start a timesheet and abandon it would accumulate zombie Draft headers forever. On the next `new_timesheet` request they'd be silently redirected back to a month-old draft. Auto-cleanup keeps the DB tidy without requiring a manual admin process.

---

### Phase 5 — Supervisor Approval Inbox (UC4 — in progress)
**What we did:**
- Built `approval_inbox` view:
  - Access guard: only levels 2, 3, 4 can access
  - Fetches all subordinates (`User.objects.filter(supervisorid=request.user)`)
  - Fetches `Submitted` and `In Progress` headers for those subordinates
  - Annotates each header with `entry_count`, `date_from`, `date_to` using `Count`, `Min`, `Max`
  - Uses `select_related('employeeid__roleid')` to avoid N+1 DB queries
  - Orders by employee name then date
- Built `approval_inbox.html`:
  - Branding header (Wesdome Gold Mines / Eagle River Mine)
  - Card count summary
  - Employee-grouped card grid using Django's `{% regroup %}` template tag
  - Each card: employee name, role, date range, entry count

**Why `{% regroup %}`?** The queryset returns flat rows (one per header). Regroup lets the template present them visually grouped by employee without needing a separate Python data structure. Cleaner than building a nested dict in the view.

**Why annotate date range from entries?** The `MainHeader` table doesn't store explicit start/end dates — those live on individual entries. Deriving `date_from = Min(startdate)` and `date_to = Max(startdate)` directly in the ORM query means the date range on each card reflects actual work dates, not arbitrary fields.

---

## Approval Flow Design (UC4)

```
Employee submits header
    → overallstatus = 'Submitted'
    → all entries linestatus = 'New'
    → header locked for employee

Supervisor opens entry and approves or rejects it
    → entry: linestatus = 'Approved' or 'Rejected'
    → entry: approvedby = supervisor, approvedat = now(), supervisornote = optional
    → header: overallstatus flips to 'In Progress' (auto, on first entry touched)
    → supervisor can stop and come back — header stays visible in inbox

Supervisor clicks "Finish Review"
    → overallstatus = 'Completed'
    → header fully locked — no further edits by anyone
    → visible to Employee (for viewing) and Payroll (for processing)
```

**Why "In Progress" state?** A real-world supervisor may review a 20-entry timesheet across two days. Without an intermediate state, a partially reviewed header looks identical to an untouched one. `In Progress` makes the inbox honest — the supervisor can see what they've started but not finished.

**Why a "Finish Review" button instead of auto-completing?** Auto-completing when all entries are processed could fire prematurely if the supervisor accidentally approves entries in the wrong order. Explicit completion puts the supervisor in control of when the record is finalised.

---

## Current URL Map

| URL | View | Who can access |
|---|---|---|
| `/login/` | `login_view` | Everyone |
| `/logout/` | `logout_view` | Authenticated |
| `/profile/` | `profile` | Authenticated |
| `/password_reset/` | `password_reset_view` | Authenticated (forced if `is_temporary`) |
| `/users/` | `user_list_view` | SysAdmin only |
| `/users/reset/<employeeid>/` | `generate_password` | SysAdmin only |
| `/timesheet/new/` | `new_timesheet` | Employee |
| `/timesheet/<pk>/` | `add_entry` | Employee (owner only) |
| `/supervisor/inbox/` | `approval_inbox` | Supervisor / Superintendent / Mine Captain |
| `/supervisor/review/<pk>/` | `review_timesheet` | Supervisor / Superintendent / Mine Captain *(next)* |

---

## What's Next (Priority Order)

### Immediate — Close UC4
1. Build `review_timesheet` view (GET: display entries, POST: approve/reject/finish_review)
2. Build `review_timesheet.html` template — entry table, per-entry approve/reject + note, Finish Review button
3. Uncomment `supervisor/review/<pk>/` in `timesheets/urls.py`
4. Wire inbox card links — replace `href="#"` with `{% url 'review_timesheet' header.mainheaderid %}`
5. Inbox two-section layout — "Awaiting Review" (Submitted) vs "In Progress" banners

### After UC4 is closed
6. Role-specific profile dashboard stats (Employees, Supervisors, Shifters see different cards)
7. Nav cleanup — hide "New Timesheet" for Supervisors, Superintendents, Payroll
8. My Timesheets page — Employee sees Draft + Submitted headers with status badges
9. My Approved / My Rejected — Employee history views
10. UC5 — Payroll view of completed timesheets

### Future / Integrations
11. Twilio SMS — Replace `print()` in `generate_password` with real SMS delivery

---

## Bugs Fixed

| Bug | Root Cause | Fix |
|---|---|---|
| `approval_inbox` not found | View placed in `users/views.py` instead of `timesheets/views.py` | Moved to correct app |
| `select_related` crash | `'employeeid_roleid'` (single underscore) — invalid syntax | Corrected to `'employeeid__roleid'` (double underscore) |
| Template rendering broken | `{% endblock %}` inside unclosed `<div>` | Closed container div before endblock |
| Entire site not loading | Dev server needed a port restart — no code error | Restarted server |
| Duplicate `home` URL name | Both `WesdomeTS/urls.py` and `users/urls.py` registered `name='home'` | Removed duplicate from `users/urls.py`, redirected login to `'profile'` |
| `@login_required` redirecting to 404 | Missing `login_url='login'` — Django defaults to `/accounts/login/` | Added `login_url='login'` to all protected views |

---

*Report generated in collaboration with Claude Code (claude-sonnet-4-6)*  
*Next report: end of next session*
