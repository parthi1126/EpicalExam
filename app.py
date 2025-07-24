from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
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
import logging
import time
from openpyxl import Workbook
from io import BytesIO

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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

def retry_on_quota_exceeded(max_attempts=5, initial_delay=1, max_delay=60):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            delay = initial_delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except gspread.exceptions.APIError as e:
                    if e.response.status_code == 429:
                        attempts += 1
                        if attempts == max_attempts:
                            raise Exception("Max retry attempts reached for Google Sheets API quota exceeded")
                        sleep_time = min(delay * (2 ** (attempts - 1)) + random.uniform(0, 0.1), max_delay)
                        logger.warning(f"Quota exceeded, retrying in {sleep_time:.2f} seconds (attempt {attempts}/{max_attempts})")
                        time.sleep(sleep_time)
                    else:
                        raise e
            return None
        return wrapper
    return decorator

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash("⚠️ You must be logged in to access this page.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '').strip()

        try:
            @retry_on_quota_exceeded()
            def get_all_data():
                return login_sheet.get_all_values()
            
            all_data = get_all_data()
            headers = [h.strip() for h in all_data[0]]
            users = [dict(zip(headers, row)) for row in all_data[1:]]

            if 'IsActive' not in headers:
                @retry_on_quota_exceeded()
                def update_is_active_column():
                    login_sheet.update_cell(1, len(headers) + 1, 'IsActive')
                update_is_active_column()
                headers.append('IsActive')
                all_data = get_all_data()
                users = [dict(zip(headers, row)) for row in all_data[1:]]

            user_row = None
            user_idx = None
            for idx, user in enumerate(users, start=2):
                sheet_email = user.get('EmployeeMailId', '').strip().lower()
                if email == sheet_email:
                    if user.get('IsActive', '').lower() == 'true':
                        flash("⚠️ You are already logged in for an exam. Please complete or logout from your active session.", "danger")
                        return redirect(url_for('login'))
                    if password == user.get('Password', '').strip():
                        user_row = user
                        user_idx = idx
                        break
            else:
                flash('Email not found', 'danger')
                return redirect(url_for('login'))

            if not user_row:
                flash('Incorrect password', 'danger')
                return redirect(url_for('login'))

            try:
                @retry_on_quota_exceeded()
                def set_is_active():
                    login_sheet.update_cell(user_idx, headers.index('IsActive') + 1, 'True')
                set_is_active()
            except Exception as e:
                logger.error(f"Error setting IsActive for {email}: {str(e)}")
                flash(f"Error setting active session: {str(e)}", "danger")
                return redirect(url_for('login'))

            session['logged_in'] = True
            session['email'] = email
            session['fullname'] = user_row.get('FullName', '')
            session['role'] = user_row.get('Role', '').lower()
            logger.info(f"User {email} logged in successfully")
            return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'instructions'))

        except Exception as e:
            logger.error(f"Login error for {email}: {str(e)}")
            flash(f"Error during login: {str(e)}", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/admin_dashboard', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("⚠️ Unauthorized access. Admins only.", "danger")
        return redirect(url_for('login'))

    try:
        @retry_on_quota_exceeded()
        def get_admin_data():
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            leaderboard_sheet = spreadsheet.worksheet("LiveLeaderboard")
            instructions_sheet = spreadsheet.worksheet("Instructions")
            leaderboard_data = leaderboard_sheet.get_all_records()
            instructions_data = instructions_sheet.col_values(1)
            return leaderboard_data, instructions_data

        leaderboard_data, instructions_data = get_admin_data()

        leaderboard = [
            {
                'name': row.get('name', ''),
                'score': row.get('score', 0),
                'rank': row.get('rank', 0)
            }
            for row in leaderboard_data
        ]

        # Handle POST request (update instructions)
        if request.method == 'POST':
            new_instructions = request.form.getlist('instructions')
            new_instructions = [instr.strip() for instr in new_instructions if instr.strip()]

            @retry_on_quota_exceeded()
            def update_instructions():
                spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
                instructions_sheet = spreadsheet.worksheet("Instructions")
                instructions_sheet.clear()
                instructions_sheet.update('A1:A' + str(len(new_instructions)), [[instr] for instr in new_instructions])

            try:
                update_instructions()
                flash("✅ Instructions updated successfully", "success")
                instructions_data = new_instructions
            except Exception as e:
                logger.error(f"Error updating instructions: {str(e)}")
                flash(f"❌ Error updating instructions: {str(e)}", "danger")

        # Handle Excel Download
        if request.args.get('download') == 'excel':
            wb = Workbook()
            ws = wb.active
            ws.title = "Leaderboard"
 
            # Write headers
            ws.append(['Name', 'Score', 'Rank'])

            # Write rows
            for entry in leaderboard:
                ws.append([entry['name'], entry['score'], entry['rank']])

            # Prepare in-memory file
            output = BytesIO()
            wb.save(output)
            output.seek(0)

            return send_file(
                output,
                download_name='leaderboard.xlsx',
                as_attachment=True,
                mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        return render_template(
            'admin_dashboard.html',
            leaderboard=leaderboard,
            instructions=instructions_data,
            fullname=session.get('fullname')
        )

    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        flash(f"❌ Error loading dashboard: {str(e)}", "danger")
        return render_template(
            'admin_dashboard.html',
            leaderboard=[],
            instructions=["Failed to load instructions"],
            fullname=session.get('fullname')
        )

@app.route('/instructions')
@login_required
def instructions():
    try:
        @retry_on_quota_exceeded()
        def get_spreadsheet_data():
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            instructions_sheet = spreadsheet.worksheet("Instructions")
            meta_sheet = spreadsheet.worksheet("TIME")
            return instructions_sheet.col_values(1), meta_sheet.get_all_records()

        instructions, meta_records = get_spreadsheet_data()
        meta = meta_records[0] if meta_records else {}
        duration = meta.get('Duration', 'N/A')
        total_questions = meta.get('TotalQuestions', 'N/A')

    except Exception as e:
        logger.error(f"Error loading instructions: {str(e)}")
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
        @retry_on_quota_exceeded()
        def get_time_data():
            time_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet("TIME")
            return time_sheet.get_all_records()

        time_data = get_time_data()
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
        logger.error(f"Error loading exam time: {str(e)}")
        return render_template('exam.html',
                              fullname=session.get('fullname'),
                              duration="10:00",
                              total_seconds=600)

@app.route('/get_questions/<test_id>')
@login_required
def get_questions(test_id):
    try:
        @retry_on_quota_exceeded()
        def get_questions_data():
            worksheet_name = f"Questions_TEST{test_id}"
            q_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
            return q_sheet.get_all_records(head=1)
        
        questions = get_questions_data()
        
        for q in questions:
            q['Type'] = q.get('Type', 'single').lower().strip()
        
        return jsonify(questions)
    except Exception as e:
        logger.error(f"Error fetching questions for test {test_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/submit_exam', methods=['POST'])
@login_required
def submit_exam():
    try:
        time.sleep(random.uniform(0.5, 2.0))
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        time_taken = data.get('time_taken')
        
        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        @retry_on_quota_exceeded()
        def get_questions_and_results():
            worksheet_name = f"Questions_TEST{test_id}"
            q_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
            questions = q_sheet.get_all_records(head=1)
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            try:
                results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
                headers = results_sheet.row_values(1)
                if "TimeTaken" not in headers:
                    results_sheet.append_row(["TimeTaken"], col=len(headers)+1)
                return questions, results_sheet
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
                return questions, results_sheet

        questions, results_sheet = get_questions_and_results()
        
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
        
        @retry_on_quota_exceeded()
        def append_results():
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

        append_results()
        
        logger.info(f"Exam submitted for {email}, test_id: {test_id}, score: {score}/{total}")
        return jsonify({
            'success': True,
            'score': score,
            'correct': correct,
            'total': total,
            'percentage': f"{percentage:.2f}%",
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        logger.error(f"Error submitting exam for {email}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/submit_answer', methods=['POST'])
@login_required
def submit_answer():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        qid = data.get('qid')
        selected_answers = data.get('selected_answers', '')
        status = data.get('status', 'answered')
        
        @retry_on_quota_exceeded()
        def manage_answers_sheet():
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            try:
                answers_sheet = spreadsheet.worksheet(f"Answers_TEST{test_id}")
            except gspread.exceptions.WorksheetNotFound:
                answers_sheet = spreadsheet.add_worksheet(
                    title=f"Answers_TEST{test_id}",
                    rows=100,
                    cols=6
                )
                answers_sheet.append_row([
                    "Timestamp", "Email", "QID", "SelectedAnswers", "Status"
                ])
            return answers_sheet
        
        answers_sheet = manage_answers_sheet()
        
        @retry_on_quota_exceeded()
        def append_answer():
            answers_sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                session.get('email'),
                qid,
                selected_answers,
                status
            ])
        
        append_answer()
        
        logger.info(f"Answer submitted for test {test_id}, qid: {qid}, user: {session.get('email')}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error submitting answer for test {test_id}: {str(e)}")
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
        
        @retry_on_quota_exceeded()
        def manage_violations_sheet():
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
            return violations_sheet
        
        violations_sheet = manage_violations_sheet()
        
        @retry_on_quota_exceeded()
        def append_violation():
            violations_sheet.append_row([
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                email,
                session.get('fullname'),
                violation,
                violation_count,
                "Warning" if violation_count < 3 else "Exam Terminated"
            ])
        
        append_violation()
        
        logger.info(f"Violation logged for {email}, test {test_id}: {violation}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error logging violation for {email}: {str(e)}")
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
        
        @retry_on_quota_exceeded()
        def manage_state_sheet():
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
            return state_sheet
        
        state_sheet = manage_state_sheet()
        
        import json
        questions_json = json.dumps(state.get('questions', []))
        
        @retry_on_quota_exceeded()
        def get_state_data():
            return state_sheet.get_all_values()
        
        all_data = get_state_data()
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
        
        @retry_on_quota_exceeded()
        def update_state():
            if user_row:
                state_sheet.update(f"A{user_row}:F{user_row}", [row_data])
            else:
                state_sheet.append_row(row_data)
        
        update_state()
        
        logger.info(f"Exam state saved for {email}, test {test_id}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error saving exam state for {email}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get_exam_state/<test_id>/<email>', methods=['GET'])
@login_required
def get_exam_state(test_id, email):
    try:
        if email != session.get('email'):
            return jsonify({'success': False, 'error': 'Unauthorized access'}), 403
        
        @retry_on_quota_exceeded()
        def get_state_sheet():
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            try:
                return spreadsheet.worksheet(f"States_TEST{test_id}")
            except gspread.exceptions.WorksheetNotFound:
                return None
        
        state_sheet = get_state_sheet()
        if not state_sheet:
            return jsonify({'success': False, 'error': 'No state found'}), 404
        
        @retry_on_quota_exceeded()
        def get_state_data():
            return state_sheet.get_all_values()
        
        all_data = get_state_data()
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
                logger.info(f"Exam state retrieved for {email}, test {test_id}")
                return jsonify({'success': True, 'state': state})
        
        return jsonify({'success': False, 'error': 'No state found'}), 404
        
    except Exception as e:
        logger.error(f"Error retrieving exam state for {email}: {str(e)}")
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
        
        @retry_on_quota_exceeded()
        def get_state_sheet():
            spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
            try:
                return spreadsheet.worksheet(f"States_TEST{test_id}")
            except gspread.exceptions.WorksheetNotFound:
                return None
        
        state_sheet = get_state_sheet()
        if not state_sheet:
            return jsonify({'success': True})  # No state to clear
        
        @retry_on_quota_exceeded()
        def get_state_data():
            return state_sheet.get_all_values()
        
        all_data = get_state_data()
        headers = all_data[0]
        email_col = headers.index("Email") + 1
        user_row = None
        for idx, row in enumerate(all_data[1:], start=2):
            if row[email_col - 1] == email:
                user_row = idx
                break
        
        if user_row:
            @retry_on_quota_exceeded()
            def delete_row():
                state_sheet.delete_rows(user_row)
            delete_row()
        
        logger.info(f"Exam state cleared for {email}, test {test_id}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error clearing exam state for {email}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clear_session', methods=['POST'])
@login_required
def clear_session():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if session.get('role') != 'admin':
            return jsonify({'success': False, 'error': 'Unauthorized: Only admins can clear sessions'}), 403
        
        if not email:
            return jsonify({'success': False, 'error': 'Missing email'}), 400
        
        @retry_on_quota_exceeded()
        def get_login_data():
            return login_sheet.get_all_values()
        
        all_data = get_login_data()
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
            @retry_on_quota_exceeded()
            def clear_is_active():
                login_sheet.update_cell(user_row, is_active_col, 'False')
            clear_is_active()
        
        logger.info(f"Session cleared for {email}")
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error clearing session for {email}: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout')
@login_required
def logout():
    try:
        email = session.get('email')
        
        @retry_on_quota_exceeded()
        def get_login_data():
            return login_sheet.get_all_values()
        
        all_data = get_login_data()
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
                @retry_on_quota_exceeded()
                def clear_is_active():
                    login_sheet.update_cell(user_row, is_active_col, 'False')
                clear_is_active()

        session.clear()
        flash('✅ Logged out', 'info')
        logger.info(f"User {email} logged out")
        return redirect(url_for('login'))
        
    except Exception as e:
        logger.error(f"Error during logout for {email}: {str(e)}")
        flash(f"Error during logout: {str(e)}", "danger")
        return redirect(url_for('login'))
