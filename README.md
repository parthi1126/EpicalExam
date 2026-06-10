<div align="center">

```
███████╗██████╗ ██╗ ██████╗ █████╗ ██╗         ███████╗██╗  ██╗ █████╗ ███╗   ███╗
██╔════╝██╔══██╗██║██╔════╝██╔══██╗██║         ██╔════╝╚██╗██╔╝██╔══██╗████╗ ████║
█████╗  ██████╔╝██║██║     ███████║██║         █████╗   ╚███╔╝ ███████║██╔████╔██║
██╔══╝  ██╔═══╝ ██║██║     ██╔══██║██║         ██╔══╝   ██╔██╗ ██╔══██║██║╚██╔╝██║
███████╗██║     ██║╚██████╗██║  ██║███████╗    ███████╗██╔╝ ██╗██║  ██║██║ ╚═╝ ██║
╚══════╝╚═╝     ╚═╝ ╚═════╝╚═╝  ╚═╝╚══════╝    ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝
```

### `> INITIALIZING SECURE EXAM ENVIRONMENT...`
### `> AUTHENTICATING SESSION... [OK]`
### `> CONNECTING TO GOOGLE SHEETS API... [OK]`
### `> SYSTEM ONLINE ✓`

---

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-2.3.3-000000?style=for-the-badge&logo=flask&logoColor=white)
![Google Sheets](https://img.shields.io/badge/Google_Sheets-API-34A853?style=for-the-badge&logo=googlesheets&logoColor=white)
![GCP Cloud Run](https://img.shields.io/badge/Deployed_on-GCP_Cloud_Run-4285F4?style=for-the-badge&logo=googlecloud&logoColor=white)
[![Live Demo](https://img.shields.io/badge/🚀_Live_App-asia--south1-FF6F00?style=for-the-badge)](https://epical-exam1-856878813474.asia-south1.run.app/)
![Gunicorn](https://img.shields.io/badge/Gunicorn-21.2.0-499848?style=for-the-badge&logo=gunicorn&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3-7952B3?style=for-the-badge&logo=bootstrap&logoColor=white)

</div>

---

## `> cat /etc/epicalexam/about.txt`

**EpicalExam** is a full-stack, cloud-native online exam portal built for **Epical Layouts** — a real-world internal assessment platform deployed on **Google Cloud Run** (`asia-south1`). It uses **Google Sheets as a live database**, making it zero-setup, zero-cost, and fully real-time. Candidates log in, read instructions, take timed MCQ-based exams, and get auto-graded — all without a single line of SQL.

> 🌐 **Live:** [epical-exam1-856878813474.asia-south1.run.app](https://epical-exam1-856878813474.asia-south1.run.app/)

> Built with Flask · Secured with session tokens · Scaled via Gunicorn · Hosted on GCP Cloud Run · Persistent via Google Sheets API

---

## `> ls -la /system/architecture/`

```
EpicalExam/
├── app.py                        ← 🧠 Core Flask application (all routes + business logic)
├── requirements.txt              ← 📦 Python dependencies
├── render.yaml                   ← 🚀 Deployment config (kept for reference; deployed on GCP Cloud Run)
├── credentials.json              ← 🔑 [NOT IN REPO] Google Service Account key
├── static/
│   ├── style.css                 ← 🎨 Login page stylesheet
│   ├── image/
│   │   ├── logo.png              ← 🖼️ Company logo (PNG)
│   │   └── logo.jpg              ← 🖼️ Company logo (JPG)
│   └── script/
│       └── script.js             ← ⚡ Client-side login validation
└── templates/
    ├── login.html                ← 🔐 Authentication entry page
    ├── instructions.html         ← 📋 Pre-exam briefing page
    ├── exam.html                 ← 🧩 Live exam interface (MCQ engine)
    └── admin_dashboard.html      ← 🛡️ Admin control panel
```

---

## `> cat /system/design/data-flow.md`

```
 ┌─────────────┐     POST /         ┌─────────────────────────────────────────┐
 │   Browser   │ ─────────────────► │         FLASK APP (app.py)              │
 │  (Candidate)│                    │                                         │
 └─────────────┘                    │  ┌──────────┐    ┌────────────────────┐ │
        │                           │  │  Session │    │  retry_on_quota    │ │
        │   GET /instructions       │  │  Store   │    │  _exceeded()       │ │
        │ ─────────────────────►    │  │ (Flask)  │    │  Exponential Back- │ │
        │                           │  └──────────┘    │  off Decorator     │ │
        │   GET /exam               │                  └────────────────────┘ │
        │ ─────────────────────►    │                           │              │
        │                           │         ┌─────────────────▼────────────┐│
        │   GET /get_questions/1    │         │    gspread Client (OAuth2)   ││
        │ ─────────────────────►    │         │                              ││
        │                           │         │  Worksheets (live DB):        ││
        │   POST /submit_exam       │         │  ├── USER                    ││
        │ ─────────────────────►    │         │  ├── Instructions            ││
        │                           │         │  ├── TIME                    ││
 ┌─────────────┐                    │         │  ├── Questions_TEST{id}      ││
 │   Browser   │                    │         │  ├── Results_TEST{id}        ││
 │   (Admin)   │   GET /admin_dash  │         │  └── LiveLeaderboard         ││
 └─────────────┘ ─────────────────► │         └──────────────────────────────┘│
                                    └─────────────────────────────────────────┘
```

---

## `> curl -X GET /api/routes --describe`

### `[POST]  /` — Authentication Gateway

**File:** `app.py → login()`

The entry point to the entire system. On POST, it:

1. Fetches all rows from the `USER` worksheet via `login_sheet.get_all_values()`
2. Normalizes email to lowercase and performs a linear scan for a matching `EmployeeMailId`
3. **Concurrent login guard** — checks `IsActive` column; if already `True`, blocks re-entry with a flash warning (prevents same user taking exam twice)
4. On password match, sets `IsActive = True` in the sheet to lock the session
5. Populates Flask `session` with `email`, `fullname`, and `role`
6. Routes to `/admin_dashboard` for admins, `/instructions` for candidates

```python
# Session payload written on successful login
session['logged_in'] = True
session['email']     = email
session['fullname']  = user_row.get('FullName', '')
session['role']      = user_row.get('Role', '').lower()
```

---

### `[GET]  /instructions` — Pre-Exam Briefing

**File:** `app.py → instructions()`  
**Guard:** `@login_required`

Fetches two worksheets in a single API call:
- `Instructions` sheet → column A values → rendered as a dynamic ordered list
- `TIME` sheet → `Duration` and `TotalQuestions` fields → displayed as exam metadata

The candidate sees their name, the exam duration, question count, and must check an acknowledgement box before a 10-second countdown begins and redirects to `/exam`.

---

### `[GET]  /exam` — Live Exam Engine

**File:** `app.py → exam()`, `templates/exam.html`  
**Guard:** `@login_required`

Fetches exam timing from the `TIME` sheet and handles two duration formats:
- `"HH:MM"` string (e.g. `"01:30"`) → parsed with `split(':')` → converted to total seconds
- Plain integer minutes → converted to seconds directly

Renders the exam shell. The actual questions load via a subsequent JS `fetch()` call to `/get_questions/<test_id>`.

**Frontend behavior (exam.html):**
- Questions render one at a time with a sidebar question navigator
- Single-choice and multi-choice (checkbox) questions both supported
- Timer counts down; at zero, exam auto-submits via `POST /submit_exam`
- Answers stored in a JS object `{ QID: "selected_option" }` until submission

---

### `[GET]  /get_questions/<test_id>` — Question Loader API

**File:** `app.py → get_questions(test_id)`  
**Guard:** `@login_required`  
**Returns:** `application/json`

Dynamically targets the worksheet `Questions_TEST{test_id}` (e.g. `Questions_TEST1`, `Questions_TEST2`), supporting multiple exam variants without any code change — just add a new sheet.

```python
worksheet_name = f"Questions_TEST{test_id}"
q_sheet = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
questions = q_sheet.get_all_records(head=1)

# Normalize question type
for q in questions:
    q['Type'] = q.get('Type', 'single').lower().strip()
```

**Expected sheet columns:** `QID`, `Question`, `OptionA`, `OptionB`, `OptionC`, `OptionD`, `Answer`, `Type`  
**Supported types:** `single` (radio), `multi` (checkbox with comma-separated correct answers)

---

### `[POST]  /submit_exam` — Auto-Grading Engine

**File:** `app.py → submit_exam()`  
**Guard:** `@login_required`  
**Accepts:** `application/json`  
**Returns:** `application/json`

The most complex route. On submission:

1. **Stagger delay** — `time.sleep(random.uniform(0.5, 2.0))` prevents Google Sheets API collisions on simultaneous submissions
2. Re-fetches questions from `Questions_TEST{test_id}` for server-side answer validation (never trusts client)
3. **Grading logic:**
   - Single-choice → case-insensitive string match against `Answer` column
   - Multi-choice → splits both correct answers and user answers by comma → compares as Python `set()` for order-independent matching
4. Lazily creates `Results_TEST{test_id}` worksheet if it doesn't exist
5. Appends a timestamped result row with: `Timestamp, Email, FullName, Score, Correct, Total, Percentage, TimeTaken, QuestionsAnswered`

```json
// Response payload
{
  "success": true,
  "score": 18,
  "correct": 18,
  "total": 25,
  "percentage": "72.00%",
  "questions_answered": 22,
  "timestamp": "2025-06-10 14:32:01"
}
```

---

### `[GET/POST]  /admin_dashboard` — Command Center

**File:** `app.py → admin_dashboard()`  
**Guard:** `@login_required` + `role == 'admin'`

**GET:** Fetches three sheets in one call — `LiveLeaderboard`, `Instructions`, and `TIME` — and renders the dashboard with real-time rankings.

**POST:** Accepts updated instructions list + exam settings (`Duration`, `TotalQuestions`) from the admin form and writes them back to Google Sheets live — no redeploy needed.

**Excel Export:** `GET /admin_dashboard?download=excel` streams a `.xlsx` file of the leaderboard directly to the browser using `pandas` + `xlsxwriter` + `BytesIO`.

```python
output = BytesIO()
with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
    df.to_excel(writer, sheet_name='Leaderboard', index=False)
output.seek(0)
return send_file(output, download_name='leaderboard.xlsx', as_attachment=True, ...)
```

---

### `[POST]  /clear_session` — Admin Session Reset

**File:** `app.py → clear_session()`  
**Guard:** `@login_required` + `role == 'admin'`  
**Returns:** `application/json`

Admin-only endpoint. Sets `IsActive = False` for a given user email in the `USER` sheet — unlocking a candidate who got stuck (browser crash, network failure) without needing a manual sheet edit.

---

### `[GET]  /logout` — Session Terminator

**File:** `app.py → logout()`  
**Guard:** `@login_required`

Clears the `IsActive` flag in the sheet (so the same candidate can re-login if needed), then destroys the Flask session with `session.clear()`.

---

## `> cat /system/design/core-mechanisms.md`

### ⚙️ Retry-on-Quota Decorator

```python
@retry_on_quota_exceeded(max_attempts=5, initial_delay=1, max_delay=60)
```

Every Google Sheets API call is wrapped with this custom decorator. It implements **exponential backoff with jitter** to handle HTTP `429 Too Many Requests` errors — common when many candidates hit the API simultaneously.

```
Attempt 1 → fail → wait ~1s
Attempt 2 → fail → wait ~2s
Attempt 3 → fail → wait ~4s
...up to max_delay=60s
```

### 🔐 Login Required Decorator

```python
@login_required
```

A standard Flask decorator that checks `session['logged_in']` before every protected route. Unauthenticated requests are redirected to `/login` with a flash warning.

### 🗃️ Google Sheets as a Live Database

| Worksheet          | Purpose                                               |
|--------------------|-------------------------------------------------------|
| `USER`             | Credential store: email, password, role, IsActive flag|
| `Instructions`     | Column A — one instruction per row, admin-editable    |
| `TIME`             | Duration (HH:MM) and TotalQuestions for the exam      |
| `Questions_TEST{N}`| MCQ data for Test variant N — fully schema-driven     |
| `Results_TEST{N}`  | Auto-created on first submission; appends result rows |
| `LiveLeaderboard`  | Real-time rankings visible in admin dashboard         |

---

## `> pip install -r requirements.txt` — Dependency Map

| Package                      | Version   | Role                                                         |
|------------------------------|-----------|--------------------------------------------------------------|
| `Flask`                      | 2.3.3     | Web framework — routing, sessions, template rendering        |
| `gspread`                    | 5.12.0    | Google Sheets Python client — read/write worksheets          |
| `oauth2client`               | 4.1.3     | Service account auth for Google APIs                         |
| `google-api-python-client`   | 2.125.0   | Core Google API client library                               |
| `google-auth`                | 2.29.0    | Modern OAuth2 authentication                                 |
| `google-auth-oauthlib`       | 1.2.0     | OAuthlib integration for google-auth                         |
| `google-auth-httplib2`       | 0.2.0     | httplib2 transport for google-auth                           |
| `gunicorn`                   | 21.2.0    | Production WSGI server (multi-worker HTTP)                   |
| `Flask-Cors`                 | 3.0.10    | Cross-Origin Resource Sharing headers                        |
| `pandas`                     | latest    | DataFrame construction for Excel export                      |
| `xlsxwriter`                 | latest    | Excel file generation engine (used with pandas)              |

---

## `> gcloud run deploy` — Deployment

This project is live on **Google Cloud Run** in the `asia-south1` (Mumbai) region — a fully managed serverless container platform. Cloud Run auto-scales to zero when idle and scales up instantly under load.

> 🌐 **Live URL:** [https://epical-exam1-856878813474.asia-south1.run.app/](https://epical-exam1-856878813474.asia-south1.run.app/)

### GCP Cloud Run Details

| Property        | Value                                             |
|-----------------|---------------------------------------------------|
| Service Name    | `epical-exam1`                                    |
| Project ID      | `856878813474`                                    |
| Region          | `asia-south1` (Mumbai, India)                     |
| Runtime         | Python 3.x container                             |
| Entry point     | `gunicorn app:app --bind 0.0.0.0:$PORT`           |
| Scaling         | Serverless — auto-scales to zero when idle        |
| Auth            | Unauthenticated (public HTTPS endpoint)           |

### Deploy via gcloud CLI

```bash
# 1. Build and push container image to Google Container Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/epicalexam

# 2. Deploy to Cloud Run
gcloud run deploy epical-exam1 \
  --image gcr.io/YOUR_PROJECT_ID/epicalexam \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars FLASK_SECRET_KEY=your-secret,GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}'
```

### Dockerfile (minimal — if not already present)

```dockerfile
FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
```

### Environment Variables (set in Cloud Run Console)

| Variable                  | Value                                    |
|---------------------------|------------------------------------------|
| `FLASK_SECRET_KEY`        | Strong random secret for session signing |
| `GOOGLE_CREDENTIALS_JSON` | Full JSON of the Google Service Account  |

> ⚠️ **Never commit `credentials.json` to git.** It is listed in `.gitignore`. On GCP Cloud Run, inject it as an environment variable via the Cloud Run console or `--set-env-vars` flag.

---

## `> ./setup.sh` — Local Development

```bash
# 1. Clone the repository
git clone https://github.com/parthi1126/EpicalExam.git
cd EpicalExam

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Place your Google Service Account key
#    Download from Google Cloud Console → IAM → Service Accounts
cp /path/to/your/credentials.json ./credentials.json

# 5. Set your spreadsheet ID in app.py
#    SPREADSHEET_ID = "your_spreadsheet_id_here"

# 6. Run the development server
python app.py
# → Running on http://127.0.0.1:5000
```

---

## `> cat /system/design/google-sheets-setup.md`

### Google Sheets Structure Required

Create a Google Spreadsheet and add these worksheets:

```
1. USER
   Columns: FullName | EmployeeMailId | Password | Role | IsActive

2. Instructions
   Column A: One instruction string per row

3. TIME
   Columns: Duration | TotalQuestions
   Row 1:   1:30     | 25

4. Questions_TEST1  (add more: Questions_TEST2, etc.)
   Columns: QID | Question | OptionA | OptionB | OptionC | OptionD | Answer | Type
   Type values: "single" or "multi"
   Multi-answer example: Answer = "A,C"

5. LiveLeaderboard
   Columns: name | score | rank

6. Results_TEST1  ← Auto-created by app on first submission
```

### Service Account Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **Google Sheets API** + **Google Drive API**
3. Create a **Service Account** → Download JSON key as `credentials.json`
4. Share your spreadsheet with the service account email (Editor access)

---

## `> cat /system/security/threat-model.md`

| Threat                          | Mitigation                                                             |
|---------------------------------|------------------------------------------------------------------------|
| Double-login / session hijack   | `IsActive` flag in USER sheet blocks concurrent logins                |
| Unauthorized route access       | `@login_required` decorator on all non-login routes                  |
| Admin-only endpoint abuse       | Role check `session['role'] == 'admin'` on admin routes              |
| Client-side answer manipulation | Server re-fetches questions and re-grades on `/submit_exam`          |
| API quota exhaustion (429)      | Exponential backoff with jitter via `retry_on_quota_exceeded()`      |
| Simultaneous submission surge   | Random delay `time.sleep(random.uniform(0.5, 2.0))` on submit       |
| Credential exposure             | `credentials.json` in `.gitignore`; injected via env vars on GCP Cloud Run |

---

## `> cat /system/design/ui-flow.md`

```
  [Login Page]
      │  POST / (email + password)
      ▼
  [Google Sheets: USER worksheet]
      │  validate → set IsActive=True → set session
      ▼
  ┌───────────────────────────────┐
  │  Role == 'admin'?             │
  │  YES → /admin_dashboard       │
  │  NO  → /instructions          │
  └───────────────────────────────┘
              │
              ▼  (Candidate path)
  [Instructions Page]
      │  Checkbox ✓ → 10s countdown → redirect
      ▼
  [Exam Page]  ← GET /get_questions/1 (JSON)
      │  MCQ interface with live timer
      │  POST /submit_exam (answers JSON)
      ▼
  [Result Modal]  ← JSON response with score/percentage
      │  session still active
      ▼
  [Logout]  → IsActive=False → session.clear()
```

---

## `> cat /system/about/author.md`

```
Parthi — Final Year B.Tech (AI & Data Science)
CITAR AIDS Department | Register No: 213223243037
Project: EpicalExam — Internal Assessment Platform
Built for Epical Layouts | Deployed on GCP Cloud Run (asia-south1, Mumbai)
Live: https://epical-exam1-856878813474.asia-south1.run.app/
```

---

<div align="center">

```
> SYSTEM STATUS: OPERATIONAL
> LAST COMMIT: PUSHED
> DEPLOYMENT: LIVE ON GCP CLOUD RUN (asia-south1)
> ENDPOINT: epical-exam1-856878813474.asia-south1.run.app
> EXAM SESSIONS: SECURE

[ EpicalExam ] — Turning Google Sheets into a production exam engine.
```

**Made with Flask, caffeine, and a single Google Spreadsheet.**

</div>
