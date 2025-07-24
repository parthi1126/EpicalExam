from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import gspread
from google.oauth2.service_account import Credentials
from functools import wraps
from datetime import datetime
import os
import json
import base64
from cachetools import TTLCache
from threading import Lock, Timer
import random

app = Flask(__name__, static_folder='static', template_folder='templates')

# Set a secret key for Flask sessions
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your-default-secret')

# Constants
SPREADSHEET_ID = "1hyoQZpD17tsTjSh1XqgAUvfZ4Nt3kwV7zxphosruXeE"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# Load base64-encoded service account JSON key from environment variable
encoded_key = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not encoded_key:
    raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set")

try:
    decoded_json = base64.b64decode(encoded_key).decode("utf-8")
    creds_info = json.loads(decoded_json)
    credentials = Credentials.from_service_account_info(creds_info, scopes=GOOGLE_SCOPES)
    gspread_client = gspread.authorize(credentials)
except Exception as e:
    raise RuntimeError(f"Error loading Google credentials: {str(e)}")

# Open the spreadsheet and worksheet
try:
    sheet = gspread_client.open_by_key(SPREADSHEET_ID)
    login_sheet = sheet.worksheet("USER")
except Exception as e:
    raise RuntimeError(f"Failed to access Google Sheet: {str(e)}")
# ---- Batching Control Logic ----

from threading import Lock, Timer
import time

MAX_BATCH_SIZE = 50         # Maximum 50 users per minute
BATCH_WINDOW = 60           # Time window in seconds

batch_lock = Lock()
active_users = set()
user_timers = {}            # Maps user_id to Timer
user_timestamps = {}        # Maps user_id to timestamp

def remove_user_from_batch(user_id):
    with batch_lock:
        active_users.discard(user_id)
        user_timers.pop(user_id, None)
        user_timestamps.pop(user_id, None)

def allow_user(user_id):
    """Check if user is allowed to proceed or should wait. Returns (allowed: bool, wait_time: int)"""
    with batch_lock:
        current_time = time.time()
        
        # If user is already active, extend their window
        if user_id in active_users:
            # Update timestamp and restart timer
            user_timestamps[user_id] = current_time
            if user_id in user_timers:
                user_timers[user_id].cancel()
            user_timers[user_id] = Timer(BATCH_WINDOW, remove_user_from_batch, [user_id])
            user_timers[user_id].start()
            return True, 0

        # If we have capacity, add user
        if len(active_users) < MAX_BATCH_SIZE:
            active_users.add(user_id)
            user_timestamps[user_id] = current_time
            timer = Timer(BATCH_WINDOW, remove_user_from_batch, [user_id])
            timer.start()
            user_timers[user_id] = timer
            return True, 0

        # Calculate wait time based on oldest user's remaining time
        oldest_user_time = min(user_timestamps.values())
        wait_time = max(1, int(BATCH_WINDOW - (current_time - oldest_user_time)))
        return False, wait_time # Cache stores data per user for 60 seconds


# Decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("⚠️ You must be logged in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Routes
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()
        session_id = f"{request.remote_addr}-{email}"

        # Rate limiting check
        allowed, wait_time = allow_user(session_id)
        if not allowed:
            flash(f"⏳ Too many users logging in. Please wait {wait_time} seconds and try again.", "warning")
            return redirect(url_for('login'))

        try:
            # Get user data in single batch
            all_data = login_sheet.get_all_values()
            headers = [h.strip() for h in all_data[0]]
            
            # Ensure IsActive column exists
            if 'IsActive' not in headers:
                login_sheet.update_cell(1, len(headers) + 1, 'IsActive')
                headers.append('IsActive')
                all_data = login_sheet.get_all_values()

            # Find user
            user_found = False
            for idx, row in enumerate(all_data[1:], start=2):
                user = dict(zip(headers, row))
                if email == user.get('EmployeeMailId', '').strip().lower():
                    user_found = True
                    if user.get('IsActive', '').lower() == 'true':
                        flash("⚠️ You are already logged in for an exam.", "danger")
                        return redirect(url_for('login'))
                    if password == user.get('Password', '').strip():
                        # Update active status
                        login_sheet.update_cell(idx, headers.index('IsActive') + 1, 'True')
                        
                        # Set session
                        session.update({
                            'logged_in': True,
                            'email': email,
                            'fullname': user.get('FullName', ''),
                            'role': user.get('Role', '').lower()
                        })
                        return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'instructions'))
                    break

            if not user_found:
                flash('Email not found', 'danger')
            else:
                flash('Incorrect password', 'danger')
                
        except Exception as e:
            flash(f"Login error: {str(e)}", "danger")
            
        return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    return "<h2>📊 Admin Dashboard</h2>"

@app.route('/instructions')
@login_required
def instructions():
    try:
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        instructions_sheet = spreadsheet.worksheet("Instructions")
        instructions = instructions_sheet.col_values(1)
        meta_sheet = spreadsheet.worksheet("TIME")
        meta_records = meta_sheet.get_all_records()
        meta = meta_records[0] if meta_records else {}
        duration = meta.get('Duration', 'N/A')
        total_questions = meta.get('TotalQuestions', 'N/A')

    except Exception as e:
        instructions = ["❌ Failed to load instructions: " + str(e)]
        duration = "N/A"
        total_questions = "N/A"

    return render_template('instructions.html',
                           fullname=session.get('fullname'),
                           instructions=instructions,
                           duration=duration,
                           total_questions=total_questions)

@app.route('/exam')
@login_required
def exam():
    try:
        time_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet("TIME")
        time_data = time_sheet.get_all_records()
        raw_duration = time_data[0]['Duration'] if time_data else "10:00"
        
        if isinstance(raw_duration, str) and ':' in raw_duration:
            hours, minutes = map(int, raw_duration.split(':'))
            total_seconds = (hours * 3600) + (minutes * 60)
            duration = f"{hours}:{minutes:02d}"
        else:
            try:
                duration_minutes = int(raw_duration)
                hours = duration_minutes // 60
                minutes = duration_minutes % 60
                total_seconds = duration_minutes * 60
                duration = f"{hours}:{minutes:02d}"
            except (ValueError, TypeError):
                raise ValueError("Invalid duration format in sheet")
        
        return render_template('exam.html', 
                              fullname=session.get('fullname'),
                              duration=duration,
                              total_seconds=total_seconds)
        
    except Exception as e:
        print(f"Error loading time: {e}")
        return render_template('exam.html',
                              fullname=session.get('fullname'),
                              duration="10:00",
                              total_seconds=600)

@app.route('/get_questions/<test_id>')
@login_required
def get_questions(test_id):
    try:
        worksheet_name = f"Questions_TEST{test_id}"
        q_sheet =gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
        questions = q_sheet.get_all_records(head=1)
        
        for q in questions:
            q['Type'] = q.get('Type', 'single').lower().strip()
        
        return jsonify(questions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
@app.route('/submit_exam', methods=['POST'])
@login_required
def submit_exam():
    try:
        # Apply batch control for quota limits
        session_id = request.remote_addr + "-" + session.get('email', 'unknown')
        allowed, wait_time = allow_user(session_id)
        if not allowed:
            return jsonify({'success': False, 'error': f'⚠️ Too many submissions right now. Please wait {wait_time} seconds.'}), 429

        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        time_taken = data.get('time_taken')

        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        worksheet_name = f"Questions_TEST{test_id}"
        q_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
        questions = q_sheet.get_all_records(head=1)

        correct = 0
        total = len(questions)

        for question in questions:
            qid = str(question['QID'])
            user_answer = data.get('answers', {}).get(qid, '')

            if question['Type'].lower() == 'multi':
                correct_answers = set(a.strip().upper() for a in question['Answer'].split(','))
                user_answers = set(a.strip().upper() for a in user_answer.split(',')) if user_answer else set()
                if correct_answers == user_answers:
                    correct += 1
            else:
                if user_answer and user_answer.strip().upper() == question['Answer'].strip().upper():
                    correct += 1

        score = correct
        percentage = (correct / total) * 100 if total > 0 else 0

        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
            headers = results_sheet.row_values(1)
            if "TimeTaken" not in headers:
                results_sheet.append_row(["TimeTaken"], col=len(headers) + 1)
        except gspread.exceptions.WorksheetNotFound:
            results_sheet = spreadsheet.add_worksheet(
                title=f"Results_TEST{test_id}",
                rows=100,
                cols=11
            )
            results_sheet.append_row([
                "Timestamp", "Email", "FullName", "Score",
                "Correct", "Total", "Percentage", "TimeTaken"
            ])

        results_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email,
            session.get('fullname'),
            score,
            correct,
            total,
            f"{percentage:.2f}%",
            time_taken
        ])

        return jsonify({
            'success': True,
            'score': score,
            'correct': correct,
            'total': total,
            'percentage': f"{percentage:.2f}%",
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def check_answer(question, user_answer):
    """Helper function to check answer correctness"""
    if not user_answer:
        return False
        
    q_type = question.get('Type', 'single').lower()
    correct_answer = question['Answer'].strip().upper()
    user_answer = user_answer.strip().upper()
    
    if q_type == 'multi':
        correct_set = set(a.strip() for a in correct_answer.split(','))
        user_set = set(a.strip() for a in user_answer.split(','))
        return correct_set == user_set
    else:
        return user_answer == correct_answer

@app.route('/submit_exam', methods=['POST'])
@login_required
def submit_exam():
    try:
        # Rate limiting
        session_id = f"{request.remote_addr}-{session.get('email', 'unknown')}"
        allowed, wait_time = allow_user(session_id)
        if not allowed:
            return jsonify({'success': False, 'error': f'⚠️ Please wait {wait_time} seconds.'}), 429

        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        time_taken = data.get('time_taken')

        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        # Get questions and calculate score
        q_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(f"Questions_TEST{test_id}")
        questions = q_sheet.get_all_records(head=1)
        answers = data.get('answers', {})
        
        correct = sum(1 for q in questions 
                     if check_answer(q, answers.get(str(q['QID']), '')))
        total = len(questions)
        percentage = (correct / total * 100) if total > 0 else 0

        # Prepare results data
        result_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email,
            session.get('fullname'),
            correct,
            correct,
            total,
            f"{percentage:.2f}%",
            time_taken
        ]

        # Write results
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
            headers = results_sheet.row_values(1)
            if "TimeTaken" not in headers:
                results_sheet.append_row(["TimeTaken"], col=len(headers) + 1)
        except gspread.exceptions.WorksheetNotFound:
            results_sheet = spreadsheet.add_worksheet(
                title=f"Results_TEST{test_id}", rows=100, cols=11)
            results_sheet.append_row([
                "Timestamp", "Email", "FullName", "Score",
                "Correct", "Total", "Percentage", "TimeTaken"
            ])

        results_sheet.append_row(result_data)

        return jsonify({
            'success': True,
            'score': correct,
            'correct': correct,
            'total': total,
            'percentage': f"{percentage:.2f}%",
            'timestamp': result_data[0]
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/log_violation', methods=['POST'])
@login_required
def log_violation():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        violation = data.get('violation')
        violation_count = data.get('violation_count')
        
        if not all([test_id, email, violation, violation_count]):
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            violations_sheet = spreadsheet.worksheet(f"Violations_TEST{test_id}")
        except gspread.exceptions.WorksheetNotFound:
            violations_sheet = spreadsheet.add_worksheet(
                title=f"Violations_TEST{test_id}", 
                rows=100, 
                cols=6
            )
            violations_sheet.append_row([
                "Timestamp", "Email", "FullName", "Violation", 
                "ViolationCount", "ActionTaken"
            ])
        
        violations_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email,
            session.get('fullname'),
            violation,
            violation_count,
            "Warning" if violation_count < 3 else "Exam Terminated"
        ])
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/save_exam_state', methods=['POST'])
@login_required
def save_exam_state():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        state = data.get('state')
        
        if not all([test_id, email, state]):
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            state_sheet = spreadsheet.worksheet(f"States_TEST{test_id}")
        except gspread.exceptions.WorksheetNotFound:
            state_sheet = spreadsheet.add_worksheet(
                title=f"States_TEST{test_id}",
                rows=100,
                cols=6
            )
            state_sheet.append_row([
                "Timestamp", "Email", "CurrentQuestion", "Questions", "TotalSeconds", "ViolationCount"
            ])
        
        import json
        questions_json = json.dumps(state.get('questions', []))
        
        all_data = state_sheet.get_all_values()
        headers = all_data[0]
        email_col = headers.index("Email") + 1
        user_row = None
        for idx, row in enumerate(all_data[1:], start=2):
            if row[email_col - 1] == email:
                user_row = idx
                break
        
        row_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email,
            str(state.get('currentQuestion', 0)),
            questions_json,
            str(state.get('totalSeconds', 0)),
            str(state.get('violationCount', 0))
        ]
        
        if user_row:
            state_sheet.update(f"A{user_row}:F{user_row}", [row_data])
        else:
            state_sheet.append_row(row_data)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_exam_state/<test_id>/<email>', methods=['GET'])
@login_required
def get_exam_state(test_id, email):
    try:
        if email != session.get('email'):
            return jsonify({'success': False, 'error': 'Unauthorized access'}), 403
        
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            state_sheet = spreadsheet.worksheet(f"States_TEST{test_id}")
        except gspread.exceptions.WorksheetNotFound:
            return jsonify({'success': False, 'error': 'No state found'}), 404
        
        all_data = state_sheet.get_all_values()
        headers = all_data[0]
        email_col = headers.index("Email") + 1
        for row in all_data[1:]:
            if row[email_col - 1] == email:
                import json
                state = {
                    'currentQuestion': int(row[headers.index("CurrentQuestion")]),
                    'questions': json.loads(row[headers.index("Questions")]),
                    'totalSeconds': int(row[headers.index("TotalSeconds")]),
                    'violationCount': int(row[headers.index("ViolationCount")]),
                    'startTime': int(datetime.now().timestamp() * 1000 - 
                                  (int(row[headers.index("TotalSeconds")]) * 1000))
                }
                return jsonify({'success': True, 'state': state})
        
        return jsonify({'success': False, 'error': 'No state found'}), 404
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clear_exam_state', methods=['POST'])
@login_required
def clear_exam_state():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        
        if not all([test_id, email]):
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            state_sheet = spreadsheet.worksheet(f"States_TEST{test_id}")
        except gspread.exceptions.WorksheetNotFound:
            return jsonify({'success': True})  # No state to clear
        
        all_data = state_sheet.get_all_values()
        headers = all_data[0]
        email_col = headers.index("Email") + 1
        user_row = None
        for idx, row in enumerate(all_data[1:], start=2):
            if row[email_col - 1] == email:
                user_row = idx
                break
        
        if user_row:
            state_sheet.delete_rows(user_row)
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clear_session', methods=['POST'])
@login_required
def clear_session():
    try:
        data = request.get_json()
        email = data.get('email')
        
        # Only allow admins to clear sessions
        if session.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Unauthorized: Only admins can clear sessions'}), 403
        
        if not email:
            return jsonify({'success': False, 'error': 'Missing email'}), 400
        
        all_data = login_sheet.get_all_values()
        headers = [h.strip() for h in all_data[0]]
        if 'IsActive' not in headers:
            return jsonify({'success': True})  # No IsActive column, nothing to clear
        
        email_col = headers.index('EmployeeMailId') + 1
        is_active_col = headers.index('IsActive') + 1
        user_row = None
        for idx, row in enumerate(all_data[1:], start=2):
            if row[email_col - 1].strip().lower() == email.lower():
                user_row = idx
                break
        
        if user_row:
            login_sheet.update_cell(user_row, is_active_col, 'False')
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout')
@login_required
def logout():
    try:
        email = session.get('email')
        
        # Clear IsActive flag
        all_data = login_sheet.get_all_values()
        headers = [h.strip() for h in all_data[0]]
        if 'IsActive' in headers:
            email_col = headers.index('EmployeeMailId') + 1
            is_active_col = headers.index('IsActive') + 1
            user_row = None
            for idx, row in enumerate(all_data[1:], start=2):
                if row[email_col - 1].strip().lower() == email:
                    user_row = idx
                    break
            if user_row:
                login_sheet.update_cell(user_row, is_active_col, 'False')

        session.clear()
        flash('✅ Logged out', 'info')
        return redirect(url_for('login'))
        
    except Exception as e:
        flash(f"Error during logout: {str(e)}", "danger")
        return redirect(url_for('login'))
