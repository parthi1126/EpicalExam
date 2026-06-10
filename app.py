from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from functools import wraps
from datetime import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
import random
import gspread.exceptions
import logging
import pandas as pd
from io import BytesIO
from flask import send_file

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-very-secure-key'  # Change to a strong key

# Google Sheets Setup
SPREADSHEET_ID = "1hyoQZpD17tsTjSh1XqgAUvfZ4Nt3kwV7zxphosruXeE"
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

try:
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    login_sheet = client.open_by_key(SPREADSHEET_ID).worksheet("USER")
except Exception as e:
    logger.error(f"Failed to initialize Google Sheets client: {str(e)}")
    raise Exception("Authentication failed. Check credentials.json, spreadsheet permissions, and system clock.")

# Retry decorator for handling 429 errors
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

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            flash(" You must be logged in to access this page.", "warning")
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
        @retry_on_quota_exceeded()
        def get_all_data():
            return login_sheet.get_all_values()

        try:
            all_data = get_all_data()
            headers = [h.strip() for h in all_data[0]]
            users = [dict(zip(headers, row)) for row in all_data[1:]]

            # Ensure IsActive column exists
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
                        flash("You are already logged in for an exam. Please complete or logout from your active session.", "danger")
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

            # Set IsActive to True
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

# Replace the existing admin_dashboard route with this updated version
@app.route('/admin_dashboard', methods=['GET', 'POST'])
@login_required
def admin_dashboard():
    if session.get('role') != 'admin':
        flash("Unauthorized access. Admins only.", "danger")
        return redirect(url_for('login'))

    try:
        @retry_on_quota_exceeded()
        def get_admin_data():
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            leaderboard_sheet = spreadsheet.worksheet("LiveLeaderboard")
            instructions_sheet = spreadsheet.worksheet("Instructions")
            time_sheet = spreadsheet.worksheet("TIME")  # Added time sheet
            leaderboard_data = leaderboard_sheet.get_all_records()
            instructions_data = instructions_sheet.col_values(1)
            time_data = time_sheet.get_all_records()  # Added time data
            return leaderboard_data, instructions_data, time_data

        leaderboard_data, instructions_data, time_data = get_admin_data()

        # Process leaderboard data
        leaderboard = [
            {
                'name': row.get('name', ''),
                'score': row.get('score', 0),
                'rank': row.get('rank', 0)
            }
            for row in leaderboard_data
        ]

        # Get duration and total questions from TIME sheet
        time_record = time_data[0] if time_data else {}
        duration = time_record.get('Duration', 'N/A')
        total_questions = time_record.get('TotalQuestions', 'N/A')

        # Handle instruction update
        if request.method == 'POST':
            new_instructions = request.form.getlist('instructions')
            new_instructions = [instr.strip() for instr in new_instructions if instr.strip()]
            total_questions = request.form.get('total_questions', total_questions)
            total_time = request.form.get('total_time', duration)

            @retry_on_quota_exceeded()
            def update_instructions_and_time():
                spreadsheet = client.open_by_key(SPREADSHEET_ID)
                instructions_sheet = spreadsheet.worksheet("Instructions")
                time_sheet = spreadsheet.worksheet("TIME")
                instructions_sheet.clear()
                instructions_sheet.update('A1:A' + str(len(new_instructions)), [[instr] for instr in new_instructions])
                time_sheet.update('A1:B2', [['Duration', 'TotalQuestions'], [total_time, total_questions]])  # Update TIME sheet

            try:
                update_instructions_and_time()
                flash("Instructions and exam settings updated successfully", "success")
                instructions_data = new_instructions
            except Exception as e:
                logger.error(f"Error updating instructions or time: {str(e)}")
                flash(f"Error updating instructions or time: {str(e)}", "danger")

        # Handle Excel download
        if request.args.get('download') == 'excel':
            df = pd.DataFrame(leaderboard)
            output = BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Leaderboard', index=False)
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
            fullname=session.get('fullname'),
            duration=duration,
            total_questions=total_questions
        )

    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        flash(f"Error loading dashboard: {str(e)}", "danger")
        return render_template(
            'admin_dashboard.html',
            leaderboard=[],
            instructions=["Failed to load instructions"],
            fullname=session.get('fullname'),
            duration='N/A',
            total_questions='N/A'
        )
    
@app.route('/instructions')
@login_required
def instructions():
    try:
        @retry_on_quota_exceeded()
        def get_spreadsheet_data():
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
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
            time_sheet = client.open_by_key(SPREADSHEET_ID).worksheet("TIME")
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
            q_sheet = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
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
        # Add a random delay to stagger submissions
        time.sleep(random.uniform(0.5, 2.0))

        data = request.get_json()
        test_id = data.get('test_id')
        email = session.get('email')
        time_taken = data.get('time_taken')
        answers = data.get('answers', {})
        
        if not test_id or not email:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        @retry_on_quota_exceeded()
        def get_questions_and_results():
            worksheet_name = f"Questions_TEST{test_id}"
            q_sheet = client.open_by_key(SPREADSHEET_ID).worksheet(worksheet_name)
            questions = q_sheet.get_all_records(head=1)
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            try:
                results_sheet = spreadsheet.worksheet(f"Results_TEST{test_id}")
                headers = results_sheet.row_values(1)
                if "TimeTaken" not in headers:
                    results_sheet.update_cell(1, len(headers) + 1, "TimeTaken")
                if "QuestionsAnswered" not in headers:
                    results_sheet.update_cell(1, len(headers) + 1, "QuestionsAnswered")
                return questions, results_sheet
            except gspread.exceptions.WorksheetNotFound:
                results_sheet = spreadsheet.add_worksheet(
                    title=f"Results_TEST{test_id}", 
                    rows=100, 
                    cols=12  # Increased to accommodate new column
                )
                results_sheet.append_row([
                    "Timestamp", "Email", "FullName", "Score", 
                    "Correct", "Total", "Percentage", "TimeTaken", 
                    "QuestionsAnswered"  # Add new column header
                ])
                return questions, results_sheet

        questions, results_sheet = get_questions_and_results()
        
        correct = 0
        total = len(questions)
        questions_answered = len([qid for qid, ans in answers.items() if ans.strip() != ''])  # Count non-empty answers
        
        for question in questions:
            qid = str(question['QID'])
            user_answer = answers.get(qid, '')
            
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
                time_taken,
                questions_answered  # Add number of questions answered
            ])

        append_results()
        
        logger.info(f"Exam submitted for {email}, test_id: {test_id}, score: {score}/{total}, questions_answered: {questions_answered}")
        return jsonify({
            'success': True,
            'score': score,
            'correct': correct,
            'total': total,
            'percentage': f"{percentage:.2f}%",
            'questions_answered': questions_answered,  # Include in response
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
        
    except Exception as e:
        logger.error(f"Error submitting exam for {email}: {str(e)}")
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
            return jsonify({'success': True})
        
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
        
        # Clear IsActive flag
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
        flash('Logged out', 'info')
        logger.info(f"User {email} logged out")
        return redirect(url_for('login'))
        
    except Exception as e:
        logger.error(f"Error during logout for {email}: {str(e)}")
        flash(f"Error during logout: {str(e)}", "danger")
        return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
