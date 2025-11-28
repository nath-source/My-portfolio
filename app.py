import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify, redirect, url_for, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from supabase import create_client, Client 
from dotenv import load_dotenv
load_dotenv()

# Configuration
app = Flask(__name__)

# --- SECURITY: ENVIRONMENT VARIABLES ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')

# 1. Database Configuration
database_url = os.environ.get('DATABASE_URL')

# Fix for Render's Postgres URL format
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# 2. Supabase Storage Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")


# Initialize Supabase Client
supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        print(f"Supabase Init Error: {e}")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'home'

# --- Database Models ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(255))
    is_admin = db.Column(db.Boolean, default=False)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    tech_stack = db.Column(db.String(200))
    link = db.Column(db.String(200))
    image_filename = db.Column(db.String(500)) 

# --- Routes ---

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def home():
    projects = Project.query.order_by(Project.id.desc()).all()
    return render_template('index.html', projects=projects)

@app.route('/api/projects')
def get_projects():
    projects = Project.query.all()
    project_list = []
    for p in projects:
        stack = p.tech_stack.split(',') if p.tech_stack else []
        project_list.append({
            'title': p.title,
            'description': p.description,
            'tech_stack': stack,
            'link': p.link,
            'image_url': p.image_filename 
        })
    return jsonify(project_list)

# --- EMAIL ROUTE ---
@app.route('/send-message', methods=['POST'])
def send_message():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        subject = request.form.get('subject')
        message = request.form.get('message')

        # FIXED: Added "or" fallback for email testing
        my_email = os.environ.get('MAIL_USERNAME')
        my_app_password = os.environ.get('MAIL_PASSWORD')

        msg = MIMEMultipart()
        msg['From'] = my_email
        msg['To'] = my_email
        msg['Subject'] = f"Portfolio Contact: {subject} from {name}"
        msg.add_header('Reply-To', email)

        body = f"Name: {name}\nEmail: {email}\nPhone: {phone}\n\nMessage:\n{message}"
        msg.attach(MIMEText(body, 'plain'))

        try:
            server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
            server.login(my_email, my_app_password)
            server.send_message(msg)
            server.quit()
            flash('Message sent successfully!', 'success')
        except Exception as e:
            print(f"Email Error: {e}")
            flash(f'Error sending message: {e}', 'danger')

        return redirect(url_for('home', _anchor='contact'))

# --- SECURE ADMIN ROUTES ---

@app.route('/secret-admin-login/<string:the_only_admin>', methods=['GET', 'POST'])
def admin_login(the_only_admin):
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            if user.is_admin:
                login_user(user)
                return redirect(url_for('admin_dashboard', the_only_admin=the_only_admin))
            else:
                flash('Access denied.')
        else:
            flash('Invalid credentials.')
        
    return render_template('admin_login.html', id=the_only_admin)

@app.route('/secret-admin-login/dashboard/<string:the_only_admin>', methods=['GET', 'POST'])
@login_required
def admin_dashboard(the_only_admin):
    if request.method == 'POST':
        image_url = "https://via.placeholder.com/800x600?text=No+Image" 

        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '' and supabase:
                try:
                    filename = secure_filename(file.filename)
                    file_content = file.read() 
                    import time
                    file_path = f"projects/{int(time.time())}_{filename}"

                    supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, file_content, {"content-type": file.content_type})
                    image_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file_path)
                    print(f"Uploaded to Supabase: {image_url}")
                except Exception as e:
                    print(f"Upload Failed: {e}")
                    flash(f"Image upload failed: {e}", "danger")
            
        selected_tech = request.form.getlist('tech_stack')
        tech_string = ",".join(selected_tech)

        new_project = Project(
            title=request.form.get('title'),
            description=request.form.get('description'),
            tech_stack=tech_string,
            link=request.form.get('link'),
            image_filename=image_url 
        )
        db.session.add(new_project)
        db.session.commit()
            
    projects = Project.query.order_by(Project.id.desc()).all()
    return render_template('admin_dashboard.html', projects=projects, admin_christiano_bernard=the_only_admin)

@app.route('/edit-project/<string:the_only_admin>/<int:id>', methods=['POST'])
@login_required
def edit_project(the_only_admin, id):
    project = Project.query.get_or_404(id)
    project.title = request.form.get('title')
    project.description = request.form.get('description')
    project.link = request.form.get('link')
    selected_tech = request.form.getlist('tech_stack')
    project.tech_stack = ",".join(selected_tech)
    
    if 'image' in request.files:
        file = request.files['image']
        if file.filename != '' and supabase:
            try:
                filename = secure_filename(file.filename)
                file_content = file.read()
                import time
                file_path = f"projects/{int(time.time())}_{filename}"
                
                supabase.storage.from_(SUPABASE_BUCKET).upload(file_path, file_content, {"content-type": file.content_type})
                project.image_filename = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file_path)
            except Exception as e:
                print(f"Update Upload Failed: {e}")
            
    db.session.commit()
    return redirect(url_for('admin_dashboard', the_only_admin=the_only_admin))

@app.route('/delete-project/<string:the_only_admin>/<int:id>', methods=['POST'])
@login_required
def delete_project(the_only_admin, id):
    project = Project.query.get_or_404(id)
    db.session.delete(project)
    db.session.commit()
    return redirect(url_for('admin_dashboard', the_only_admin=the_only_admin))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

with app.app_context():
    db.create_all()
    
    # FIXED: Added "or" fallback to prevent NoneType error on password generation
    admin_email = os.environ.get('ADMIN_EMAIL')
    admin_password = os.environ.get('ADMIN_PASSWORD')

    user = User.query.filter_by(email=admin_email).first()
    
    if not user:
        hashed_pw = generate_password_hash(admin_password, method='pbkdf2:sha256')
        admin = User(email=admin_email, password=hashed_pw, is_admin=True)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin user created: {admin_email}")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)