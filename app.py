# --- Main imports from Login System ---
# --- Main imports from Login System ---
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import fitz 
from geopy.geocoders import Nominatim
import json
import requests
from openai import OpenAI
# --- Imports from Medical Advice App ---
import pytesseract
from PIL import Image
from dotenv import load_dotenv
import google.generativeai as genai # <-- KEEP ONLY ONE

# --- Advanced Feature Imports (Mail, Scheduler) ---
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
# --- App Configuration ---
# ... (rest of your app.py file)

# --- App Configuration ---
load_dotenv() # Load environment variables
app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
try:
    openai_client = OpenAI() # This automatically reads the OPENAI_API_KEY from your .env
    print("OpenAI client configured successfully for DALL-E image generation.")
except Exception as e:
    openai_client = None
    print(f"WARNING: Could not configure OpenAI client. Image generation will fail. Error: {e}")

EXERCISEDB_API_KEY = os.getenv('EXERCISEDB_API_KEY')
# --- Upload Folder Configuration (from Medical Advice App) ---
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'docx'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16 MB max file size

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # Ensure the upload folder exists

# --- Tesseract Configuration (from Medical Advice App) ---
# Make sure to adjust this path if yours is different
try:
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    os.environ["TESSDATA_PREFIX"] = r"C:\Program Files\Tesseract-OCR\tessdata"
except Exception:
    print("WARNING: Tesseract not found at C:\\Program Files\\Tesseract-OCR\\tesseract.exe. OCR will fail.")
    print("Please install Tesseract OCR and/or update the path in app.py if you need OCR functionality.")


# --- Database Configuration (MySQL) ---
USER = 'root'
PASSWORD = ''
HOST = '127.0.0.1' # Use 127.0.0.1 for Windows development
PORT = 3306
DATABASE_NAME = 'hospital_db'

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{USER}:{PASSWORD}@{HOST}:{PORT}/{DATABASE_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- Mail Config (Flask-Mail) ---
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'true').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config.get('MAIL_USERNAME'))
mail = Mail(app)

# --- APScheduler Config ---
scheduler = BackgroundScheduler(timezone="UTC")
scheduler.start()

# --- Database Models (No Changes Here) ---
class Hospital(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    address = db.Column(db.String(200))
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    doctors = db.relationship('Doctor', backref='hospital', lazy=True)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True)
    phone = db.Column(db.String(15), unique=True)
    password_hash = db.Column(db.String(200), nullable=False)
    specialization = db.Column(db.String(100))
    hospital_id = db.Column(db.Integer, db.ForeignKey('hospital.id'), nullable=False)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

class Patient(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(200), nullable=False)
    profiles = db.relationship('PatientProfile', backref='patient', lazy=True)
    def set_password(self, password): self.password_hash = generate_password_hash(password)
    def check_password(self, password): return check_password_hash(self.password_hash, password)

# This is the "db class" that stores the medical history

class PatientProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    profile_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    aadhar_no = db.Column(db.String(12), unique=True, nullable=True)
    age = db.Column(db.Integer)
    gender = db.Column(db.String(10))
    medical_history = db.Column(db.Text, nullable=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)

# In app.py

class PatientDocument(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    document_type = db.Column(db.String(50), nullable=False)
    upload_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    
    # --- ADD THIS NEW COLUMN AND RELATIONSHIP ---
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=True) # Nullable = True, because patient can upload
    doctor = db.relationship('Doctor', backref='uploaded_documents')
    # --- END OF ADDITION ---
    
    patient = db.relationship('Patient', backref=db.backref('documents', lazy=True))
class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_name = db.Column(db.String(100), nullable=False)
    patient_email = db.Column(db.String(120), nullable=False)
    patient_phone = db.Column(db.String(20), nullable=False)
    appointment_date = db.Column(db.Date, nullable=False)
    appointment_time = db.Column(db.String(10), nullable=False)
    reason_for_visit = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='Booked')
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    # --- ADD THIS NEW COLUMN AND RELATIONSHIP ---
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    patient = db.relationship('Patient', backref='appointments')
    # --- END OF ADDED COLUMN ---
    doctor = db.relationship('Doctor', backref='appointments')

class MedicalRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    record_date = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    notes = db.Column(db.Text, nullable=False) # Doctor's diagnosis, notes
    prescription = db.Column(db.Text, nullable=True) # Medication details
    
    # Foreign keys to link the record
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), unique=True, nullable=False) # Each record is for one specific appointment

    # Relationships
    doctor = db.relationship('Doctor', backref='medical_records')
    patient = db.relationship('Patient', backref='medical_records')
    appointment = db.relationship('Appointment', backref=db.backref('medical_record', uselist=False))

# --- MERGED ROUTES START HERE ---
def generate_password(length=8):
    """Generates a random password."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for i in range(length))

# --- ADD THIS NEW HELPER FUNCTION TO APP.PY ---
# 3. HELPER FUNCTIONS (Email, AI, Scheduling)
# ====================================================================

def send_email(to_email, subject, template, **kwargs):
    """Helper to send emails."""
    if not app.config.get('MAIL_SERVER'):
        print(f"Mail not configured. Would send to {to_email} with subject '{subject}'")
        return
    try:
        msg = Message(subject, recipients=[to_email])
        msg.html = render_template(template, **kwargs)
        mail.send(msg)
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Error sending email: {e}")

def schedule_appointment_reminders(appointment):
    """Schedules email reminders for an appointment."""
    try:
        # Convert appointment time from 'HH:MM AM/PM' to a datetime object
        appt_dt_str = f"{appointment.appointment_date} {appointment.appointment_time}"
        appt_dt = datetime.strptime(appt_dt_str, '%Y-%m-%d %I:%M %p') # Use %I for 12-hour format
        
        # Schedule a reminder 24 hours before the appointment
        reminder_time_24h = appt_dt - timedelta(hours=24)
        if reminder_time_24h > datetime.now():
            job_id = f'appt_{appointment.id}_reminder_24h'
            scheduler.add_job(
                func=send_email,
                trigger='date',
                run_date=reminder_time_24h,
                args=[appointment.patient_email, 'Appointment Reminder', 'emails/reminder.html'],
                kwargs={'appointment': appointment},
                id=job_id,
                replace_existing=True
            )
            print(f"Scheduled 24-hour reminder for appointment {appointment.id} at {reminder_time_24h}")

    except Exception as e:
        print(f"Error scheduling reminder for appointment {appointment.id}: {e}")

def cancel_scheduled_reminders(appointment_id):
    """Removes any scheduled jobs for a given appointment ID."""
    job_id = f'appt_{appointment_id}_reminder_24h'
    try:
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            print(f"Removed scheduled reminders for cancelled appointment {appointment_id}")
    except Exception as e:
        print(f"Could not remove job {job_id}. It may have already run or not existed. Error: {e}")

def get_ai_analysis(extracted_text: str) -> str:
    """
    Takes extracted text and returns an AI-generated summary using the configured Gemini model.
    Raises an exception if the model is not configured or fails.
    """
    if not gemini_model:
        raise Exception("AI analysis service is not configured.")

    prompt = f"""
    You are a helpful medical assistant. Your role is to analyze a medical document for a patient and explain it in simple, easy-to-understand language. Do not provide a direct diagnosis. Use clean Markdown for formatting with headings and bullet points.

    Based on the following document text, provide a summary with these exact sections:
    
    ### Summary of Document
    Start with a brief, one-sentence summary of what this document is (e.g., "This is a report for a chest X-ray.").

    ### Key Findings
    Use a bulleted list to highlight the most important results, measurements, or observations mentioned in the report.

    ### Explanation of Terms
    Use a bulleted list to explain any complex medical terms from the findings in simple language. If there are no complex terms, state "All terms are standard."

    ### Recommendations (if mentioned)
    Use a bulleted list to summarize any next steps, precautions, or follow-up advice mentioned in the document. If none are mentioned, state "No specific recommendations were mentioned in this report."

    Here is the document text:
    ---
    {extracted_text}
    ---
    """
    
    response = gemini_model.generate_content(prompt)
    
    if response and response.candidates:
        return response.candidates[0].content.parts[0].text.strip()
    else:
        raise Exception("Could not get a valid analysis from the AI model.")
    
# --- Routes for the Medical Advice / Main Landing Page ---
@app.route('/')
def index():
    # This is the main landing page of your whole project.
    # It used to be your separate "index.html" for the advice app.
    return render_template("index.html")

@app.route("/medical_advice")
def medical_advice():
    return render_template("medical_advice.html")

@app.route("/inperson")
def inperson():
    hospitals = Hospital.query.order_by(Hospital.name).all()
    return render_template("inperson.html", hospitals=hospitals)


# --- REPLACE your entire old /upload route with this ---
# --- REPLACE your entire /upload route with this corrected version ---

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part in the request."}), 400
        
    file = request.files["file"]

    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({"error": "No selected file or file type not allowed."}), 400

    analysis_response = "" # Initialize variable outside the try block

    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)
        
        extracted_text = ""
        if filename.lower().endswith('.pdf'):
            with fitz.open(filepath) as pdf_doc:
                for page in pdf_doc:
                    extracted_text += page.get_text()
        elif filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg']:
            image = Image.open(filepath)
            extracted_text = pytesseract.image_to_string(image)
        
        if not extracted_text.strip():
            # Use the "analysis" key for consistency
            return jsonify({"analysis": "Could not find any text in the document."})
        
        # Call the helper function and store the result
        analysis_response = get_ai_analysis(extracted_text)
        
    except Exception as e:
        print(f"Error in /upload route: {e}")
        return jsonify({"error": str(e)}), 500

    # Return the successful response OUTSIDE the try...except block
    return jsonify({"analysis": analysis_response})

@app.route('/upload_document', methods=['POST'])
def upload_document():
    if session.get('user_type') != 'patient' or 'user_id' not in session:
        flash('You must be logged in as a patient to upload documents.', 'danger')
        return redirect(url_for('patient_login'))

    if 'document' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(url_for('patient_dashboard'))
        
    file = request.files['document']
    doc_type = request.form.get('document_type')

    if file.filename == '':
        flash('No selected file.', 'warning')
        return redirect(url_for('patient_dashboard'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # To make filenames unique, prepend the patient ID and a timestamp
        unique_filename = f"{session['user_id']}_{int(datetime.now().timestamp())}_{filename}"
        
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        # Save file info to the database
        new_document = PatientDocument(
            filename=unique_filename,
            document_type=doc_type,
            patient_id=session['user_id']
        )
        db.session.add(new_document)
        db.session.commit()
        
        flash('Document uploaded successfully!', 'success')
    else:
        flash('File type not allowed.', 'danger')
        
    return redirect(url_for('patient_dashboard'))


# This is an API endpoint that your JavaScript will call
@app.route('/api/doctors/<int:hospital_id>')
def get_doctors_for_hospital(hospital_id):
    doctors = Doctor.query.filter_by(hospital_id=hospital_id).all()
    
    # Convert the list of doctor objects into a list of dictionaries
    doctor_list = []
    for doctor in doctors:
        doctor_list.append({
            'id': doctor.id,
            'name': doctor.name,
            'specialization': doctor.specialization
            # Add any other doctor info you want to display
        })
    
    return jsonify(doctors=doctor_list)


# --- ADD this new route to your app.py ---
# This route handles the form submission
# --- REPLACE your old /book_appointment route with this ---
# ====================================================================
# FINAL AND COMPLETE BOOKING & CANCELLATION ROUTES
# ====================================================================

@app.route('/book_appointment', methods=['POST'])
def book_appointment():
    """
    Handles the multi-step appointment booking form.
    - Creates a new patient account if one doesn't exist.
    - Creates the appointment record.
    - Sends an immediate email confirmation.
    - Schedules a future email reminder.
    """
    try:
        data = request.get_json()
        phone = data['phone']
        email = data['email']
        is_new_user = False

        # Step 1: Find or Create the Patient
        patient = Patient.query.filter(or_(Patient.phone == phone, Patient.email == email)).first()
        
        if not patient:
            is_new_user = True
            dob_string = data.get('dob')
            if not dob_string:
                return jsonify({'success': False, 'message': 'Date of Birth is required for new patients.'}), 400

            # Create the main patient record for login
            patient = Patient(
                name=f"{data['firstName']} {data.get('lastName', '')}",
                phone=phone,
                email=email
            )
            patient.set_password(dob_string) # DOB string is the password
            db.session.add(patient)
            db.session.flush()  # Use flush to get the patient.id for the profile

            # Create the associated patient profile
            profile = PatientProfile(
                profile_name=f"{patient.name}'s Profile",
                date_of_birth=datetime.strptime(dob_string, '%Y-%m-%d').date(),
                aadhar_no=data.get('aadhar') if data.get('aadhar') else None,
                patient_id=patient.id
            )
            db.session.add(profile)

        # Step 2: Create the Appointment
        new_appointment = Appointment(
            patient_name=f"{data['firstName']} {data.get('lastName', '')}",
            patient_email=email,
            patient_phone=phone,
            appointment_date=datetime.strptime(data['date'], '%Y-%m-%d').date(),
            appointment_time=data['time'], # Assumes format like '02:00 PM'
            reason_for_visit=data.get('reason', ''),
            doctor_id=data['doctorId'],
            patient_id=patient.id
        )
        db.session.add(new_appointment)
        db.session.commit()  # Commit to get the final new_appointment.id

        # Step 3: Trigger Notifications
        # We run this in a try-except so a notification failure doesn't break the booking
        try:
            # Send immediate email confirmation
            send_email(
                to_email=new_appointment.patient_email,
                subject=f"Appointment Confirmed at {new_appointment.doctor.hospital.name}",
                template='emails/confirmation.html',
                appointment=new_appointment
            )
            # Schedule a reminder for the future
            schedule_appointment_reminders(new_appointment)
        except Exception as e:
            print(f"NOTIFICATION ERROR for appt {new_appointment.id}: {e}")

        # Step 4: Send Success Response to Frontend
        response_data = {
            'success': True, 
            'message': 'Appointment booked successfully! A confirmation email has been sent.',
            'new_user': is_new_user
        }
        return jsonify(response_data)
        
    except Exception as e:
        db.session.rollback()
        print(f"CRITICAL BOOKING ERROR: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while booking. Please check your details and try again.'}), 500


@app.route('/cancel_appointment/<int:appt_id>', methods=['POST'])
def cancel_appointment(appt_id):
    """
    Handles a patient's request to cancel an appointment.
    - Updates the appointment status to 'Cancelled'.
    - Removes any pending scheduled reminders for that appointment.
    """
    # Security: Ensure a patient is logged in
    if 'user_id' not in session or session.get('user_type') != 'patient':
        flash("You must be logged in to manage appointments.", "danger")
        return redirect(url_for('patient_login'))
    
    # Find the appointment and ensure it belongs to the logged-in patient
    appointment_to_cancel = Appointment.query.filter_by(
        id=appt_id, 
        patient_id=session['user_id']
    ).first()

    if appointment_to_cancel:
        # Step 1: Update the appointment status
        appointment_to_cancel.status = 'Cancelled'
        
        # Step 2: Cancel any scheduled reminders for this appointment
        cancel_scheduled_reminders(appointment_to_cancel.id)
        
        db.session.commit()
        flash("Your appointment has been successfully cancelled.", "success")
    else:
        flash("Appointment not found or you do not have permission to cancel it.", "danger")

    return redirect(url_for('patient_dashboard'))# --- THE CRITICAL CHANGE: THE LOGIN ROUTE ---
@app.route("/login")
def login():
    # When a user clicks a "Login" button on your main page,
    # this redirects them to the start of the hospital login system.
    return redirect(url_for('hospital_selection'))


# --- Routes for the Hospital/Doctor/Patient Login System ---
@app.route('/hospitals')
def hospital_selection():
    hospitals = Hospital.query.all()
    return render_template('hospital_selection.html', hospitals=hospitals)

@app.route('/hospital_register', methods=['GET', 'POST'])
def hospital_register():
    if request.method == 'POST':
        name, address, email, password = request.form.get('name'), request.form.get('address'), request.form.get('email'), request.form.get('password')
        if Hospital.query.filter_by(email=email).first():
            flash('This email is already registered.')
            return redirect(url_for('hospital_register'))
        new_hospital = Hospital(name=name, address=address, email=email)
        new_hospital.set_password(password)
        db.session.add(new_hospital)
        db.session.commit()
        flash('Hospital registered successfully! Please log in.')
        return redirect(url_for('hospital_login'))
    return render_template('hospital_register.html')

@app.route('/hospital_login', methods=['GET', 'POST'])
def hospital_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        hospital = Hospital.query.filter_by(email=email).first()
        if hospital and hospital.check_password(password):
            session['user_id'] = hospital.id
            session['user_type'] = 'hospital'
            return redirect(url_for('doctor_register'))
        else:
            flash('Invalid hospital credentials.')
    return render_template('hospital_login.html')

# --- Doctor Routes ---
@app.route('/doctor_register', methods=['GET', 'POST'])
def doctor_register():
    if session.get('user_type') != 'hospital':
        flash('Please log in as a hospital to register doctors.')
        return redirect(url_for('hospital_login'))
    if request.method == 'POST':
        name, email, phone, password, specialization = request.form.get('name'), request.form.get('email'), request.form.get('phone'), request.form.get('password'), request.form.get('specialization')
        hospital_id = session.get('user_id')
        if Doctor.query.filter((Doctor.email == email) | (Doctor.phone == phone)).first():
            flash('Email or phone already registered.')
            return redirect(url_for('doctor_register'))
        doctor = Doctor(name=name, email=email, phone=phone, specialization=specialization, hospital_id=hospital_id)
        doctor.set_password(password)
        db.session.add(doctor)
        db.session.commit()
        flash('Doctor registered successfully!')
        return redirect(url_for('doctor_register'))
    hospital = Hospital.query.get(session.get('user_id'))
    return render_template('doctor_register.html', hospital=hospital)

@app.route('/doctor_login', methods=['GET', 'POST'])
def doctor_login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        password = request.form.get('password')
        doctor = Doctor.query.filter((Doctor.email == identifier) | (Doctor.phone == identifier)).first()
        if doctor and doctor.check_password(password):
            session['user_id'] = doctor.id
            session['user_type'] = 'doctor'
            return redirect(url_for('doctor_dashboard'))
        else:
            flash('Invalid doctor credentials.')
    return render_template('doctor_login.html')

# --- MODIFY your existing /doctor_dashboard route ---
@app.route('/doctor_dashboard')
def doctor_dashboard():
    if session.get('user_type') != 'doctor':
        return redirect(url_for('doctor_login'))
        
    doctor_id = session.get('user_id')
    doctor = Doctor.query.get(doctor_id)
    
    # --- NEW LOGIC TO FETCH APPOINTMENTS ---
    # Order by date and time to show upcoming appointments first
    upcoming_appointments = Appointment.query.filter(
        Appointment.doctor_id == doctor_id,
        Appointment.appointment_date >= datetime.utcnow().date()
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).all()
    
    return render_template(
        'doctor_dashboard.html', 
        doctor=doctor,
        appointments=upcoming_appointments
    )
# --- Patient Routes (Password-based, No OTP) ---
@app.route('/patient_register', methods=['GET', 'POST'])
def patient_register():
    if request.method == 'POST':
        name, phone, email, password = request.form.get('name'), request.form.get('phone'), request.form.get('email'), request.form.get('password')
        if Patient.query.filter((Patient.phone == phone) | (Patient.email == email)).first():
            flash('Phone number or email already registered.')
            return redirect(url_for('patient_register'))
        patient = Patient(name=name, phone=phone, email=email)
        patient.set_password(password)
        db.session.add(patient)
        profile = PatientProfile(profile_name=f"{name}'s Profile", age=request.form.get('age'), gender=request.form.get('gender'), patient=patient)
        db.session.add(profile)
        db.session.commit()
        flash('Registration successful! Please log in.')
        return redirect(url_for('patient_login'))
    return render_template('patient_register.html')

# --- REPLACE your old patient_login function with this new one ---
# --- REPLACE your old patient_login route with this ---
@app.route('/patient_login', methods=['GET', 'POST'])
def patient_login():
    if request.method == 'POST':
        identifier = request.form.get('identifier')
        dob_string = request.form.get('dob') # The password is the DOB string 'YYYY-MM-DD'

        if not identifier or not dob_string:
            flash('Please provide both your identifier and date of birth.', 'warning')
            return redirect(url_for('patient_login'))

        # Find the patient by their email or phone
        patient = Patient.query.filter(or_(Patient.email == identifier, Patient.phone == identifier)).first()

        # --- CRITICAL CHANGE: Check the password hash ---
        # We check if a patient was found AND if their hashed password matches the dob_string
        if patient and patient.check_password(dob_string):
            # Login successful
            session['user_id'] = patient.id
            session['user_type'] = 'patient'
            
            if len(patient.profiles) > 1:
                return redirect(url_for('select_profile'))
            else:
                session['profile_id'] = patient.profiles[0].id
                return redirect(url_for('patient_dashboard'))
        else:
            # If no match or password check fails, the credentials are wrong
            flash('Invalid credentials. Please check your details and try again.', 'danger')
            return redirect(url_for('patient_login'))
            
    return render_template('patient_login.html')
# --- Shared & Profile Routes ---
@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.')
    return redirect(url_for('hospital_selection'))

# --- REPLACE your entire old /patient_dashboard route with this ---
# This is the backend function that writes data to the 'medical_history' field

@app.route('/update_medical_history', methods=['POST'])
def update_medical_history():
    # 1. Security: Make sure a patient is logged in and has a profile selected.
    if 'user_id' not in session or session.get('user_type') != 'patient':
        return redirect(url_for('patient_login'))
    if 'profile_id' not in session:
        return redirect(url_for('select_profile'))

    # 2. Find the correct PatientProfile object in the database.
    profile = PatientProfile.query.get(session.get('profile_id'))
    if not profile:
        flash("Could not find your profile.", "danger")
        return redirect(url_for('patient_dashboard'))

    # 3. Get the text from the <textarea name="medical_history"> in the form.
    new_history_text = request.form.get('medical_history')

    # 4. Update the 'medical_history' attribute of the Python object.
    profile.medical_history = new_history_text
    
    # 5. Commit the change, which saves it permanently to the database.
    db.session.commit()
    
    # 6. Send feedback to the user and reload the page.
    flash("Your medical history has been updated successfully!", "success")
    return redirect(url_for('patient_dashboard'))

# This is the backend function that reads the 'medical_history' field and sends it to the page

@app.route('/patient_dashboard')
def patient_dashboard():
    # ... (security and profile checks) ...
    patient_id = session.get('user_id')
    patient = Patient.query.get_or_404(patient_id)
    active_profile = PatientProfile.query.get_or_404(session.get('profile_id'))
    
    # Logic to control the upload form
    can_upload_documents = True 

    # Logic to fetch all documents
    all_documents = PatientDocument.query.filter_by(patient_id=patient_id).order_by(PatientDocument.upload_date.desc()).all()
    
    # Logic to fetch upcoming appointments
    upcoming_appointments = Appointment.query.filter(
        Appointment.patient_id == patient_id,
        Appointment.appointment_date >= datetime.utcnow().date(),
        Appointment.status == 'Booked'
    ).order_by(Appointment.appointment_date, Appointment.appointment_time).all()
    
    # This is where the data is sent to the template
    return render_template(
        'patient_dashboard.html', 
        patient=patient, 
        profile=active_profile, # The 'active_profile' object contains the medical_history
        has_recent_appointment=can_upload_documents,
        documents=all_documents,
        upcoming_appointments=upcoming_appointments,
        now=datetime.utcnow() 
    )
# --- ADD THIS NEW ROUTE for cancelling appointments ---

# --- ADD a new route to serve the uploaded files securely ---
from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    # Security check: ensure only logged-in patients can see their own files
    if 'user_id' not in session or session.get('user_type') != 'patient':
        return "Access denied", 403
        
    # Find the document in the database
    doc = PatientDocument.query.filter_by(filename=filename, patient_id=session['user_id']).first()
    
    if not doc:
        return "File not found or access denied", 404
        
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
@app.route('/select_profile')
def select_profile():
    if session.get('user_type') != 'patient':
        return redirect(url_for('patient_login'))
    patient = Patient.query.get(session.get('user_id'))
    return render_template('select_profile.html', profiles=patient.profiles)

@app.route('/set_profile/<int:profile_id>')
def set_profile(profile_id):
    if session.get('user_type') != 'patient':
        return redirect(url_for('patient_login'))
    profile = PatientProfile.query.get(profile_id)
    if profile and profile.patient_id == session.get('user_id'):
        session['profile_id'] = profile_id
        return redirect(url_for('patient_dashboard'))
    flash('Invalid profile selected.')
    return redirect(url_for('select_profile'))
@app.route('/doctor/view_patient/<int:patient_id>/from_appt/<int:appointment_id>')
def view_patient_details(patient_id, appointment_id):
    # --- Security Check 1: Ensure user is a doctor ---
    if session.get('user_type') != 'doctor':
        flash("Access denied.", "danger")
        return redirect(url_for('doctor_login'))

    doctor_id = session.get('user_id')

    # --- Security Check 2: Ensure this patient has an appointment with THIS doctor ---
    appointment = Appointment.query.filter_by(
        id=appointment_id, 
        doctor_id=doctor_id, 
        patient_id=patient_id
    ).first()

    if not appointment:
        flash("You do not have permission to view this patient's records.", "danger")
        return redirect(url_for('doctor_dashboard'))

    # If security checks pass, fetch all patient data
    patient = Patient.query.get_or_404(patient_id)
    
    # Fetch all of the patient's past documents and medical records (notes from doctors)
    past_documents = PatientDocument.query.filter_by(patient_id=patient_id).order_by(PatientDocument.upload_date.desc()).all()
    past_medical_records = MedicalRecord.query.filter_by(patient_id=patient_id).order_by(MedicalRecord.record_date.desc()).all()

    return render_template(
        'view_patient.html', 
        patient=patient,
        appointment=appointment,
        past_documents=past_documents,
        past_medical_records=past_medical_records
    )

@app.route('/doctor/add_medical_record', methods=['POST'])
def add_medical_record():
    # Security Check
    if session.get('user_type') != 'doctor':
        return "Access Denied", 403

    doctor_id = session.get('user_id')
    patient_id = request.form.get('patient_id')
    appointment_id = request.form.get('appointment_id')
    notes = request.form.get('notes')
    prescription = request.form.get('prescription')
    
    # Verify this doctor is allowed to add a record for this appointment
    appointment = Appointment.query.filter_by(id=appointment_id, doctor_id=doctor_id, patient_id=patient_id).first()
    if not appointment:
        flash("Invalid request.", "danger")
        return redirect(url_for('doctor_dashboard'))
        
    # Check if a record already exists for this appointment
    if appointment.medical_record:
        flash("A medical record for this appointment already exists.", "warning")
        return redirect(url_for('view_patient_details', patient_id=patient_id, appointment_id=appointment_id))

    # Create and save the new medical record
    new_record = MedicalRecord(
        notes=notes,
        prescription=prescription,
        doctor_id=doctor_id,
        patient_id=patient_id,
        appointment_id=appointment_id
    )
    db.session.add(new_record)
    db.session.commit()

    flash("Medical record added successfully.", "success")
    return redirect(url_for('view_patient_details', patient_id=patient_id, appointment_id=appointment_id))



# --- Initialize the OpenAI client right after your app config ---
# It will automatically read the OPENAI_API_KEY from your .env file
# Get API key from .env
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # Initialize the Gemini model to be used for analysis
    gemini_model = genai.GenerativeModel("gemini-2.5-flash") 
    print("Gemini configured successfully.")
except Exception as e:
    gemini_model = None
    print(f"WARNING: Could not configure Gemini. Analysis will fail. Error: {e}")
# --- END OF GEMINI CONFIG BLOCK ---


# --- ADD THIS NEW ROUTE for the doctor to upload files ---
@app.route('/doctor/upload_for_patient', methods=['POST'])
def doctor_upload_for_patient():
    if session.get('user_type') != 'doctor':
        return "Access Denied", 403

    patient_id = request.form.get('patient_id')
    doc_type = request.form.get('document_type')
    file = request.files.get('document')
    
    # Security: Verify this doctor is allowed to upload for this patient
    # (e.g., they have an appointment together)
    appointment_exists = Appointment.query.filter_by(
        doctor_id=session['user_id'],
        patient_id=patient_id
    ).first()

    if not appointment_exists:
        flash("You do not have permission to upload documents for this patient.", "danger")
        return redirect(url_for('doctor_dashboard'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        unique_filename = f"doc_{patient_id}_{int(datetime.now().timestamp())}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
        
        new_document = PatientDocument(
            filename=unique_filename,
            document_type=doc_type,
            patient_id=patient_id,
            doctor_id=session['user_id'] # Link to the uploading doctor
        )
        db.session.add(new_document)
        db.session.commit()
        flash('Document uploaded for patient successfully!', 'success')
    else:
        flash('Invalid file or file type.', 'danger')
        
    # Redirect back to the patient view page, which requires appointment_id
    return redirect(url_for('view_patient_details', patient_id=patient_id, appointment_id=appointment_exists.id))


# --- REPLACE your entire old /analyze_document route with this ---
import fitz # PyMuPDF

# --- REPLACE your entire old /analyze_document route with this ---
@app.route('/analyze_document/<int:doc_id>', methods=['POST'])
def analyze_document(doc_id):
    if session.get('user_type') != 'patient':
        return jsonify({"error": "Access Denied"}), 403

    doc = PatientDocument.query.filter_by(id=doc_id, patient_id=session['user_id']).first()
    if not doc:
        return jsonify({"error": "Document not found or access denied"}), 404

    try:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
        extracted_text = ""
        
        if doc.filename.lower().endswith('.pdf'):
            with fitz.open(filepath) as pdf_doc:
                for page in pdf_doc:
                    extracted_text += page.get_text()
        elif doc.filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg']:
            image = Image.open(filepath)
            extracted_text = pytesseract.image_to_string(image)
        else:
            return jsonify({"error": "Unsupported file type for analysis."}), 400
        
        if not extracted_text.strip():
            # Return an "analysis" key to match what this frontend expects
            return jsonify({"analysis": "Could not find any text in the document to analyze."})

        # --- Call the new helper function ---
        analysis_response = get_ai_analysis(extracted_text)
        
        # The frontend for this page expects an "analysis" key
        return jsonify({"analysis": analysis_response})

    except Exception as e:
        print(f"Analysis Error: {e}")
        return jsonify({"error": f"An error occurred during analysis: {e}"}), 500
# --- ADD THIS NEW ROUTE for contextual Q&A to app.py ---

@app.route('/ask_about_document', methods=['POST'])
def ask_about_document():
    # Security check: User must be a logged-in patient
    if session.get('user_type') != 'patient':
        return jsonify({"error": "Access Denied"}), 403

    data = request.get_json()
    doc_id = data.get('doc_id')
    question = data.get('question')

    if not all([doc_id, question]):
        return jsonify({"error": "Missing document ID or question."}), 400

    # Security check: Ensure the document belongs to this patient
    doc = PatientDocument.query.filter_by(id=doc_id, patient_id=session['user_id']).first()
    if not doc:
        return jsonify({"error": "Document not found or access denied."}), 404

    # --- Extract text from the document AGAIN to provide context to the AI ---
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], doc.filename)
    extracted_text = ""
    try:
        if doc.filename.lower().endswith('.pdf'):
            with fitz.open(filepath) as pdf_doc:
                for page in pdf_doc:
                    extracted_text += page.get_text()
        elif doc.filename.lower().split('.')[-1] in ['png', 'jpg', 'jpeg']:
            image = Image.open(filepath)
            extracted_text = pytesseract.image_to_string(image)
        else:
            # This case should ideally not be reached if analysis worked before
            return jsonify({"error": "Unsupported file type."}), 400
            
    except Exception as e:
        print(f"Error re-extracting text: {e}")
        return jsonify({"error": "Could not read the document to answer the question."}), 500

    if not extracted_text.strip():
        return jsonify({"response": "I couldn't find any text in the original document to reference."})

    # --- Create the contextual prompt for Gemini ---
    try:
        if not gemini_model:
            raise Exception("AI service is not configured.")

        # --- THIS IS THE NEW, MORE INTELLIGENT PROMPT ---
        prompt = f"""
        You are a helpful and knowledgeable medical assistant. Your task is to answer a patient's question. You have two modes of answering:

        1.  **If the patient's question can be answered directly from the text of their medical document**, you must base your answer on that text.
        2.  **If the patient's question is a general medical question (like asking for a definition or general advice) that is NOT in the document**, you should use your general knowledge to provide a helpful, safe, and informative answer.

        **CRITICAL RULES:**
        -   You must NEVER provide a new diagnosis.
        -   Your tone should be reassuring and easy to understand.
        -   Always include a disclaimer if you are providing general information not found in the report. For example: "While this report doesn't go into detail, here is a general explanation..."
        -   If asked for advice on how to "cure" a condition that the report says is not present (e.g., "No active disease"), you should first point out the good news from the report and then provide general wellness advice.

        Here is the full text of the medical document for context:
        --- DOCUMENT START ---
        {extracted_text}
        --- DOCUMENT END ---

        Here is the patient's question:
        "{question}"

        Now, analyze the question and the document, and provide the best possible answer based on the rules above.
        """
        # --- END OF THE NEW PROMPT ---
        
        response = gemini_model.generate_content(prompt)
        
        if response and response.candidates:
            answer = response.candidates[0].content.parts[0].text.strip()
        else:
            answer = "I was unable to process your question at this time."

        return jsonify({"response": answer})

    except Exception as e:
        print(f"Contextual Chat Error: {e}")
        return jsonify({"error": "An error occurred while getting the answer."}), 500
# --- START: Routes for Emergency Guide Page ---

# 1. Route to serve the main emergency guide page
@app.route('/emergency')
def emergency_guide():
    """Renders the main emergency guide and chatbot page."""
    return render_template('emergency_guide.html')


# 2. API route for getting first aid instructions when a button is clicked
@app.route('/get_guide', methods=['POST'])
def get_emergency_guide():
    """Provides AI-generated first aid steps for a specific emergency."""
    data = request.get_json()
    emergency_type = data.get('emergency')

    if not emergency_type:
        return jsonify({"error": "No emergency type specified."}), 400

    if not gemini_model:
        return jsonify({"error": "AI service is not configured."}), 500

    try:
        prompt = f"""
        You are an AI First Aid Instructor. Your instructions must be simple, clear, and numbered, using Markdown for formatting. 
        The very first step must always be a bolded instruction like '**1. Call Emergency Services Immediately.**'. 
        Provide a step-by-step first aid guide for the following situation: "{emergency_type}".
        Keep the language very simple, using short sentences and bullet points, as if talking to someone in a panic.
        """
        response = gemini_model.generate_content(prompt)
        guide_text = response.candidates[0].content.parts[0].text.strip()
        return jsonify({"guide": guide_text})
    except Exception as e:
        print(f"Emergency Guide Error: {e}")
        return jsonify({"error": "Could not generate guide at this time."}), 500


# 3. API route to simulate calling an ambulance
@app.route('/call_ambulance', methods=['POST'])
def call_ambulance():
    """Simulates a call for an ambulance and reverse geocodes the location."""
    data = request.get_json()
    name = data.get('name')
    phone = data.get('phone')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    # Simple validation
    if not all([name, phone]):
        return jsonify({
            "success": False,
            "message": "Name and Phone Number are required."
        }), 400

    # --- NEW: Reverse Geocoding with geopy ---
    human_readable_address = "Not Provided"
    if latitude and longitude:
        try:
            # Initialize the geolocator with a unique user_agent
            geolocator = Nominatim(user_agent="anon_healthcare_app_v1")
            
            # Use the reverse method to get address from coordinates
            location = geolocator.reverse(f"{latitude}, {longitude}", exactly_one=True, language='en')
            
            if location:
                human_readable_address = location.address
            else:
                human_readable_address = "Could not determine address for the given coordinates."
                
        except Exception as e:
            print(f"Geopy Error: {e}")
            human_readable_address = "Error looking up address."

    # In a real-world application, you would integrate with an emergency dispatch API here.
    # For this simulation, we will just print the data to the server console.
    print("=" * 40)
    print("!!! AMBULANCE DISPATCH REQUEST !!!")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Caller Name: {name}")
    print(f"Caller Phone: {phone}")
    
    if latitude and longitude:
        print(f"Browser Location (PRECISE): {latitude}, {longitude}")
        print(f"Detected Address (APPROXIMATE): {human_readable_address}")
        print(f"Google Maps Link: https://www.google.com/maps?q={latitude},{longitude}")
    else:
        print("Browser Location: NOT PROVIDED or DENIED")
    print("=" * 40)
    
    return jsonify({
        "success": True, 
        "message": "Ambulance dispatched! Help is on the way. Your details have been logged."
    })


# 4. API route for handling the interactive chatbot messages
@app.route('/chat_response', methods=['POST'])
def chat_response():
    """Processes a user's message from the chatbot and returns an AI response."""
    data = request.get_json()
    user_message = data.get('message')

    if not user_message:
        return jsonify({"response": "I'm sorry, I didn't receive a message."}), 400

    if not gemini_model:
        return jsonify({"error": "AI service is not configured."}), 500

    try:
        prompt = f"""
        You are an Emergency First Aid Assistant Chatbot. Your role is to:
        1. Analyze the user's emergency situation described in their message.
        2. Provide immediate, clear, and actionable first aid guidance using simple language and Markdown lists.
        3. ALWAYS prioritize advising the user to call emergency services if the situation sounds serious.
        4. Be calm and reassuring.
        
        User's emergency situation: "{user_message}"
        
        Provide a helpful, step-by-step response. Start with the most critical action.
        """
        
        response = gemini_model.generate_content(prompt)
        bot_response = response.candidates[0].content.parts[0].text.strip()
        
        return jsonify({"response": bot_response})
    except Exception as e:
        print(f"Chatbot Error: {e}")
        return jsonify({"error": "Sorry, I could not process your request right now."}), 500

# --- END: Routes for Emergency Guide Page ---
# --- REPLACE your old get_exercise_plan function with this ---
# Environment variable for ExerciseDB API Key
# In app.py, REPLACE the get_exercise_names function

def get_exercise_names(medical_conditions: str) -> list:
    if not gemini_model:
        raise Exception("AI service is not configured.")

    available_exercises = [
        "walking", "arm_circles", "wall_push_up", "seated_leg_raise", 
        "bodyweight_squat", "glute_bridge", "jumping_jacks", "plank",
        "cat_cow_stretch", "bird_dog"
    ]
    
    prompt = f"""
    You are an AI fitness advisor. Your task is to select 5 safe, low-impact exercises for a person with these medical conditions: "{medical_conditions}".
    You MUST choose 5 exercises ONLY from the following list: {available_exercises}
    Your response MUST be ONLY a JSON-formatted list of strings.
    """
    
    response = gemini_model.generate_content(prompt)
    
    if response and response.candidates:
        json_string = response.candidates[0].content.parts[0].text.strip().replace("`", "").replace("json", "")
        try:
            exercise_list = json.loads(json_string)
            # Final check to ensure AI didn't invent an exercise
            return [ex for ex in exercise_list if ex in available_exercises]
        except json.JSONDecodeError:
            raise Exception("AI did not return a valid JSON list.")
    else:
        raise Exception("Could not get a valid response from the AI model.")
    
# In app.py, REPLACE the /get_exercise_plan route

@app.route('/get_exercise_plan', methods=['POST'])
def generate_exercise_plan_route():
    # Security checks remain the same
    if session.get('user_type') != 'patient':
        return jsonify({"error": "Access Denied"}), 403

    profile = PatientProfile.query.filter_by(patient_id=session['user_id']).first()
    if not profile or not profile.medical_history:
        return jsonify({"error": "Please add medical history to generate a plan."})

    # Check if the DALL-E client was configured
    if not openai_client:
        return jsonify({"error": "Image generation service is not configured."}), 500

    try:
        # --- Step 1: Get exercise names from Gemini AI (same as before) ---
        print("[INFO] Getting exercise names from Gemini...")
        exercise_names = get_exercise_names(profile.medical_history)
        print(f"[INFO] Gemini suggested: {exercise_names}")

        # --- Step 2: Generate an image for EACH exercise name using DALL-E ---
        exercise_details_list = []
        
        # Define a consistent visual style for all images
        image_style_prompt = (
            "A clean, minimalist, vector line art illustration on a plain white background. "
            "The image should clearly and simply demonstrate the exercise form. "
            "Anatomically correct, simple black lines, no color, no shadows."
        )

        for name in exercise_names:
            print(f"[INFO] Generating image for '{name}' via DALL-E...")
            
            # Create a detailed prompt for the image generation model
            dalle_prompt = f"An illustration of a person performing the '{name.replace('_', ' ')}' exercise. {image_style_prompt}"

            # Make the API call to DALL-E
            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=dalle_prompt,
                size="1024x1024", # A standard square size
                quality="standard",
                n=1,
            )
            
            # The API returns a temporary URL to the generated image
            image_url = response.data[0].url
            
            exercise_details_list.append({
                "name": name.replace("_", " ").title(),
                "gifUrl": image_url, # This is now the LIVE URL from DALL-E
                "equipment": "Body Weight",
                "instructions": ["Follow the motion shown in the illustration.", "Perform 10-12 repetitions."]
            })
        
        disclaimer = "**Disclaimer:** This is an AI-generated suggestion. Always consult your doctor before starting any new exercise program."

        return jsonify({"plan": exercise_details_list, "disclaimer": disclaimer})

    except Exception as e:
        print(f"--- [CRITICAL ERROR] Live Image Generation Failed: {e} ---")
        return jsonify({"error": "Could not generate a complete exercise plan at this time."}), 500
@app.route('/debug/generate_exercise_assets')
def generate_exercise_assets():
    # Security: This route should only be accessible in debug mode
    if not app.debug:
        return "This feature is only available in debug mode.", 403

    if not openai_client:
        return "OpenAI client is not configured. Cannot generate images.", 500

    # --- Configuration ---
    # This list MUST match the names in your get_exercise_names() AI prompt
    EXERCISE_LIST = [
        "walking", "arm_circles", "wall_push_up", "seated_leg_raise", 
        "bodyweight_squat", "glute_bridge", "jumping_jacks", "plank",
        "cat_cow_stretch", "bird_dog"
    ]
    OUTPUT_FOLDER = os.path.join(app.static_folder, 'exercises') # Correctly points to 'static/exercises'
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    IMAGE_STYLE_PROMPT = (
        "A clean, minimalist, vector line art illustration on a plain white background. "
        "The image should clearly and simply demonstrate the exercise form. "
        "Anatomically correct, simple black lines, no color, no shadows. "
        "Focus on the movement and proper posture."
    )

    results = []

    for exercise_name in EXERCISE_LIST:
        file_path = os.path.join(OUTPUT_FOLDER, f"{exercise_name}.png")
        if os.path.exists(file_path):
            message = f"✅ Image for '{exercise_name}' already exists. Skipping."
            print(message)
            results.append(message)
            continue

        prompt = f"An illustration of a person performing the '{exercise_name.replace('_', ' ')}' exercise. {IMAGE_STYLE_PROMPT}"
        print(f"Generating image for: '{exercise_name}'...")
        
        try:
            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            image_url = response.data[0].url
            image_data = requests.get(image_url).content
            
            with open(file_path, 'wb') as handler:
                handler.write(image_data)
            
            message = f"✅ Successfully generated and saved image to {file_path}"
            print(message)
            results.append(message)
            
        except Exception as e:
            message = f"❌ Failed to generate image for '{exercise_name}'. Error: {e}"
            print(message)
            results.append(message)
    
    # Return a simple HTML page with the results
    return f"""
    <h1>Exercise Image Generation Complete</h1>
    <ul>
        {''.join(f'<li>{res}</li>' for res in results)}
    </ul>
    """

# --- Main execution ---
if __name__ == '__main__':
    # Important: Before running for the first time, make sure you have:
    # 1. A MySQL database named 'hospital_db' created.
    # 2. Run the commands in your terminal to create the tables:
    #    - set FLASK_APP=app.py  (or export FLASK_APP=app.py)
    #    - flask shell
    #    - from app import db
    #    - db.create_all()
    #    - exit()
    app.run(debug=True, host='0.0.0.0')