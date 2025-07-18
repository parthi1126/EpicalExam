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
user_sheet = gspread_client.open_by_key(GOOGLE_SHEET_ID).worksheet("USER")

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
        email = request.form.get('email')
        password = request.form.get('password')
        users = login_sheet.get_all_records(head=1)

        for user in users:
            if str(user.get('EmployeeMailId', '')).strip().lower() == email.lower():
                if password == str(user.get('Password', '')).strip():
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

@app.route('/submit_answer', methods=['POST'])
@login_required
def submit_answer():
    try:
        data = request.get_json()
        email = session['email']
        test_id = data.get('test_id')
        qid = data.get('qid')
        selected = ','.join(data.get('selected_answers', []))
        status = data.get('status', 'answered')

        answer_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(f"Answers_{test_id}")
        timestamp = datetime.now().isoformat()

        records = answer_sheet.get_all_records(head=1)
        found = False
        for i, row in enumerate(records, start=2):
            if row.get('Email') == email and str(row.get('QID')) == str(qid):
                answer_sheet.update(f"C{i}:E{i}", [[selected, timestamp, status]])
                found = True
                break

        if not found:
            answer_sheet.append_row([email, qid, selected, timestamp, status])

        return jsonify({'success': True})

    except Exception as e:
        print("Error in /submit_answer:", str(e))
        return jsonify({'error': 'Server error during submission.'}), 500

@app.route('/get_questions/<test_id>')
@login_required
def get_questions(test_id):
    try:
        q_sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet(f"Questions_{test_id}")
        questions = q_sheet.get_all_records(head=1)
        return jsonify(questions)
    except Exception as e:
        print("Error in /get_questions:", str(e))
        return jsonify({'error': 'Failed to load questions.'}), 500

@app.route('/logout')
def logout():
    session.clear()
    flash('✅ Logged out', 'info')
    return redirect(url_for('login'))