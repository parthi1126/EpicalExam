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
GOOGLE_SHEET_ID = "1hyoQZpD17tsTjSh1XqgAUvfZ4Nt3kwV7zxphosruXeE"
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
login_sheet = gspread_client.open_by_key(GOOGLE_SHEET_ID).worksheet("USER")

# Decorator for login required
ef login_required(f):
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
        email = request.form.get('email')
        password = request.form.get('password')

        users = login_sheet.get_all_records(head=1)

        for user in users:
            sheet_email = str(user.get('EmployeeMailId', '')).strip().lower()
            sheet_password = str(user.get('Password', '')).strip()

            if email.lower() == sheet_email:
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
@login_required
def instructions():
    return render_template('instructions.html', fullname=session.get('fullname'))


@app.route('/exam')
@login_required
def exam():
    return render_template('exam.html', fullname=session.get('fullname'))




@app.route('/get_questions/<test_id>')
@login_required
def get_questions(test_id):
    try:
        # For TEST01 use Questions_TEST01
        worksheet_name = f"Questions_TEST{test_id}"
        
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        q_sheet = spreadsheet.worksheet(worksheet_name)
        questions = q_sheet.get_all_records(head=1)
        
        return jsonify(questions)
        
    except gspread.exceptions.WorksheetNotFound:
        return jsonify({'error': f'Worksheet {worksheet_name} not found'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/submit_exam', methods=['POST'])
@login_required
def submit_exam():
    try:
        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        
        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400
        
        # Get the test results sheet
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        
        # Try to find existing results sheet or create new
        try:
            results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
        except gspread.exceptions.WorksheetNotFound:
            # Create a new worksheet if it doesn't exist
            results_sheet = spreadsheet.add_worksheet(
                title=f"Results_TEST{test_id}", 
                rows=100, 
                cols=10
            )
            # Add headers
            results_sheet.append_row([
                "Timestamp", "Email", "FullName", "Score", 
                "Correct", "Total", "Percentage"
            ])
        
        # Get questions to calculate score
        q_sheet = spreadsheet.worksheet(f"Questions_TEST{test_id}")
        questions = q_sheet.get_all_records(head=1)
        
        # Get user's answers (you'll need to store these somewhere during the test)
        # For now, we'll just calculate a dummy score
        # In a real implementation, you'd track answers during the test
        correct = 0
        total = len(questions)
        
        # Calculate score (this is simplified - you'd compare actual answers)
        # For demo purposes, we'll assume 70% correct
        correct = int(total * 0.7)
        score = correct
        percentage = (correct / total) * 100 if total > 0 else 0
        
        # Record the result
        results_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            email,
            session.get('fullname'),
            score,
            correct,
            total,
            f"{percentage:.2f}%"
        ])
        
        return jsonify({
            'success': True,
            'score': score,
            'correct': correct,
            'total': total,
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
