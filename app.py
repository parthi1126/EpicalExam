from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from functools import wraps
from datetime import datetime
import os
import json
import base64


app = Flask(__name__, static_folder='static', template_folder='templates')

app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default-secret-key')

# Constants
SPREADSHEET_ID = "1hyoQZpD17tsTjSh1XqgAUvfZ4Nt3kwV7zxphosruXeE"
GOOGLE_SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

# Load and decode base64-encoded service account JSON from env
encoded = os.getenv("GOOGLE_CREDENTIALS_JSON")
if not encoded:
    raise ValueError("Missing GOOGLE_CREDENTIALS_JSON environment variable")

decoded = base64.b64decode(encoded).decode("utf-8")
creds_dict = json.loads(decoded)
google_creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, GOOGLE_SCOPE)
gspread_client = gspread.authorize(google_creds)

# Access the USER worksheet
login_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet("USER")

# Decorator for login required

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

        # Get data with proper header handling
        all_data = login_sheet.get_all_values()
        headers = [h.strip() for h in all_data[0]]  # Clean headers
        users = []
        for row in all_data[1:]:
            users.append(dict(zip(headers, row)))

        for user in users:
            sheet_email = user.get('EmployeeMailId', '').strip().lower()
            sheet_password = user.get('Password', '').strip()  # Now works with cleaned header
            
            if email == sheet_email:
                if password == sheet_password:
                    session['logged_in'] = True
                    session['email'] = email
                    session['fullname'] = user.get('FullName', '')
                    session['role'] = user.get('Role', '').lower()
                    return redirect(url_for('admin_dashboard' if session['role'] == 'admin' else 'instructions'))
                else:
                    flash('Incorrect password', 'danger')
                    break
        else:
            flash('Email not found', 'danger')

        return redirect(url_for('login'))

    return render_template('login.html')



@app.route('/admin_dashboard')

@login_required


def admin_dashboard():
    return "<h2>📊 Admin Dashboard</h2>"


@app.route('/instructions')
def instructions():
    try:
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)

        # Fetch instructions
        instructions_sheet = spreadsheet.worksheet("Instructions")
        instructions = instructions_sheet.col_values(1)

        # Fetch metadata
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
def exam():
    try:
        # Get time from TIME sheet
        time_sheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet("TIME")
        time_data = time_sheet.get_all_records()
        
        # Get raw duration value from sheet
        raw_duration = time_data[0]['Duration'] if time_data else "10:00"
        
        # Handle both cases: "HH:MM" format or total minutes (integer)
        if isinstance(raw_duration, str) and ':' in raw_duration:
            # Case 1: "HH:MM" format (e.g., "90:00")
            hours, minutes = map(int, raw_duration.split(':'))
            total_seconds = (hours * 3600) + (minutes * 60)
            duration = f"{hours}:{minutes:02d}"  # Reformat for display
        else:
            # Case 2: Total minutes (e.g., 90)
            try:
                duration_minutes = int(raw_duration)
                hours = duration_minutes // 60
                minutes = duration_minutes % 60
                total_seconds = duration_minutes * 60
                duration = f"{hours}:{minutes:02d}"  # Convert to "H:MM" format
            except (ValueError, TypeError):
                raise ValueError("Invalid duration format in sheet")
        
        return render_template('exam.html', 
                            fullname=session.get('fullname'),
                            duration=duration,
                            total_seconds=total_seconds)
        
    except Exception as e:
        print(f"Error loading time: {e}")
        # Default values if there's an error
        return render_template('exam.html',
                            fullname=session.get('fullname'),
                            duration="10:00",
                            total_seconds=600)




@app.route('/get_questions/<test_id>')
def get_questions(test_id):
    try:
        worksheet_name = f"Questions_TEST{test_id}"
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
        
        questions = spreadsheet.get_all_records(head=1)
        
        # Ensure Type field is properly formatted
        for q in questions:
            q['Type'] = q.get('Type', 'single').lower().strip()
        
        return jsonify(questions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500



@app.route('/submit_exam', methods=['POST'])
def submit_exam():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        time_taken = data.get('time_taken')
        
        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        worksheet_name = f"Questions_TEST{test_id}"
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
        questions = spreadsheet.get_all_records(head=1)
        
        correct = 0
        total = len(questions)
        
        for question in questions:
            qid = str(question['QID'])
            user_answer = data.get('answers', {}).get(qid, '')
            
            # Handle both single and multi-select questions
            if question['Type'].lower() == 'multi':
                # Normalize answers - remove spaces and make uppercase
                correct_answers = set(a.strip().upper() for a in question['Answer'].split(','))
                user_answers = set(a.strip().upper() for a in user_answer.split(',')) if user_answer else set()
                
                # All-or-nothing scoring (full point only if exact match)
                if correct_answers == user_answers:
                    correct += 1
                # Alternative: Partial credit (1 point per correct answer, max 1 point)
                # correct += min(1, len(correct_answers & user_answers) / len(correct_answers))
            else:  # single answer
                if user_answer and user_answer.strip().upper() == question['Answer'].strip().upper():
                    correct += 1
        
        score = correct
        percentage = (correct / total) * 100 if total > 0 else 0
        
        # Get or create results sheet
        spreadsheet = gspread_client.open_by_key(SPREADSHEET_ID)
        try:
            results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
            headers = results_sheet.row_values(1)
            if "TimeTaken" not in headers:
                results_sheet.insert_cols([["TimeTaken"]], len(headers)+1)
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
        
        # Record the submission
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
@app.route('/logout')
def logout():
    session.clear()
    flash('✅ Logged out', 'info')
    return redirect(url_for('login'))
@app.route('/submit_answer', methods=['POST'])
@login_required
def submit_answer():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        qid = data.get('qid')
        selected_answers = data.get('selected_answers', [])
        status = data.get('status', 'answered')
        
        # In a real implementation, you'd store these answers in a session or database
        # For now, we'll just return success
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/log_violation', methods=['POST'])
def log_violation():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        violation = data.get('violation')
        violation_count = data.get('violation_count')
        
        if not all([test_id, email, violation, violation_count]):
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        # Get or create violations sheet
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
        
        # Record the violation
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