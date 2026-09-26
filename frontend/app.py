from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_file
from flask_socketio import SocketIO, emit
import sqlite3
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
import json
import logging
import psutil
import os
import shutil
from werkzeug.utils import secure_filename
import time
import threading
import pickle
import uuid
from sklearn.preprocessing import LabelEncoder, MinMaxScaler
import base64

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Load all anomaly detection models ---
models = {}
model_files = {
    'logon': 'ml mode/anomaly_logon.pkl',
    'device': 'ml mode/anomaly_device.pkl',
    'file': 'ml mode/anomaly_file.pkl',
    'http': 'ml mode/anomaly_http.pkl'
}

for name, filename in model_files.items():
    try:
        with open(filename, 'rb') as f:
            models[name] = pickle.load(f)
        logger.info(f"Anomaly detection model '{name}' loaded successfully")
    except FileNotFoundError:
        logger.error(f"Model file not found: {filename}. Anomaly detection for '{name}' will be disabled.")
        models[name] = None
    except Exception as e:
        logger.error(f"Error loading model '{name}': {e}")
        models[name] = None


# Ensure directories exist
os.makedirs("users/admin", exist_ok=True)
os.makedirs("logs", exist_ok=True)
for filename in ['usb_alerts.txt', 'anomaly_alerts.txt', 'admin_activity.log', 'file_access_logs.txt']:
    if not os.path.exists(f"users/admin/{filename}"):
        open(f"users/admin/{filename}", 'w').close()

# Initialize anomaly logs
for log_type in ['logon', 'file', 'http', 'device']:
    log_file = f"logs/anomaly_{log_type}.log"
    if not os.path.exists(log_file):
        open(log_file, 'w').close()

# --- User Online Status and Risk Score Tracking ---
online_users = {}
client_sids = {}
webcam_watchers = {}
user_risk_scores = {} # NEW: For dynamic risk scoring

# --- NEW: Anomaly Point Values ---
ANOMALY_POINTS = {
    'logon': 5,
    'device': 5,
    'file': 3,
    'http': 3,
    'usb_file_copy': 7
}

def risk_score_decay():
    """Background thread to slowly decrease risk scores over time."""
    while True:
        with app.app_context():
            for user_id in list(user_risk_scores.keys()):
                if user_risk_scores[user_id] > 0:
                    user_risk_scores[user_id] -= 1 # Decay by 1 point

                    # Persist the decayed score so the database stays in sync
                    # with the in-memory risk score used by the dashboard.
                    try:
                        with sqlite3.connect("../users.db") as conn:
                            conn.execute(
                                "UPDATE user_data SET risk_score = ? WHERE user_id = ?",
                                (user_risk_scores[user_id], user_id)
                            )
                            conn.commit()
                    except Exception as e:
                        logger.error(f"Error persisting decayed risk score for {user_id}: {e}")

                    socketio.emit('update_risk_score', {
                        'user_id': user_id,
                        'score': user_risk_scores[user_id]
                    })
            socketio.sleep(3600) # Decay every hour

def check_offline_users():
    while True:
        try:
            offline_threshold = time.time() - 30
            offline_user_ids = [user_id for user_id, last_seen in list(online_users.items()) if last_seen < offline_threshold]
            
            for user_id in offline_user_ids:
                if user_id in online_users:
                    del online_users[user_id]
                    if user_id in client_sids:
                        del client_sids[user_id]
                    socketio.emit('user_offline', {'user_id': user_id})
                    logger.info(f"User {user_id} is offline.")
        except Exception as e:
            logger.error(f"Error in check_offline_users: {e}")
        socketio.sleep(15)

threading.Thread(target=check_offline_users, daemon=True).start()
threading.Thread(target=risk_score_decay, daemon=True).start() # NEW: Start decay thread

def cleanup_logs_periodically():
    """Background thread to clean up old logs every hour"""
    while True:
        try:
            cleanup_old_logs()
        except Exception as e:
            logger.error(f"Error in cleanup_logs_periodically: {e}")
        socketio.sleep(3600)  # Clean up every hour



# Database Functions (remain unchanged)
def init_admin_db():
    try:
        conn = sqlite3.connect("admin.db")
        c = conn.cursor()
        c.execute("CREATE TABLE IF NOT EXISTS admin_password (id INTEGER PRIMARY KEY, password TEXT)")
        c.execute("SELECT COUNT(*) FROM admin_password")
        if c.fetchone()[0] == 0:
            c.execute("INSERT INTO admin_password VALUES (1, 'p@ssw0rd')")
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error initializing admin DB: {e}")

def init_user_db():
    """Initializes the main user database and loads risk scores."""
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        
        # Add risk_score column if it doesn't exist (for backward compatibility)
        try:
            c.execute("ALTER TABLE user_data ADD COLUMN risk_score INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Column already exists
        
        # Add usb_count column if it doesn't exist
        try:
            c.execute("ALTER TABLE user_data ADD COLUMN usb_count INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass # Column already exists

        c.execute("""
            CREATE TABLE IF NOT EXISTS user_data (
                user_id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT, pc_name TEXT,
                platform TEXT, accepted INTEGER DEFAULT 0, logs TEXT DEFAULT '[]',
                network_traffic TEXT DEFAULT '{}', file_operations TEXT DEFAULT '[]',
                removable_media_transfers TEXT DEFAULT '[]', user_activity TEXT DEFAULT '[]',
                login_time TEXT DEFAULT '', logout_time TEXT DEFAULT '', login_duration INTEGER DEFAULT 0,
                internet_status TEXT DEFAULT '', usb_count INTEGER DEFAULT 0,
                system_info TEXT DEFAULT '{}', locations TEXT DEFAULT '[]',
                risk_score INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        
        c.execute("SELECT user_id, risk_score FROM user_data")
        for row in c.fetchall():
            user_risk_scores[row[0]] = row[1] if row[1] is not None else 0

        conn.close()
    except Exception as e:
        logger.error(f"Error initializing user DB: {e}")

def init_user_databases(username):
    user_folder = get_user_folder(username)
    web_activity_db = os.path.join(user_folder, "web_activity.db")
    try:
        conn = sqlite3.connect(web_activity_db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS web_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                title TEXT,
                visit_time TEXT,
                duration TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_web_activity_time ON web_activity(visit_time)")
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing web activity DB for {username}: {e}")
    finally:
        conn.close()
    
    online_data_db = os.path.join(user_folder, "online_data.db")
    try:
        conn = sqlite3.connect(online_data_db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS website_visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                title TEXT,
                timestamp TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS file_downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT,
                filename TEXT,
                timestamp TEXT,
                size TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_visits_time ON website_visits(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_downloads_time ON file_downloads(timestamp)")
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing online data DB for {username}: {e}")
    finally:
        conn.close()
    
    network_activity_db = os.path.join(user_folder, "network_activity.db")
    try:
        conn = sqlite3.connect(network_activity_db)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS network_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                protocol TEXT,
                remote_ip TEXT,
                port INTEGER,
                status TEXT,
                pid INTEGER,
                interface TEXT,
                sent_bytes INTEGER,
                received_bytes INTEGER,
                timestamp TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS packet_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interface TEXT,
                remote_ip TEXT,
                bytes_sent INTEGER,
                bytes_recv INTEGER,
                bytes_sent_rate REAL,
                bytes_recv_rate REAL,
                packets_sent INTEGER,
                packets_recv INTEGER,
                packets_sent_rate REAL,
                packets_recv_rate REAL,
                errors_in INTEGER,
                errors_out INTEGER,
                drops_in INTEGER,
                drops_out INTEGER,
                connection_count INTEGER,
                ports TEXT,
                protocols TEXT,
                processes TEXT,
                total_bytes_sent INTEGER,
                total_bytes_recv INTEGER,
                timestamp TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_network_activity_time ON network_activity(timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_packet_analysis_time ON packet_analysis(timestamp)")
        conn.commit()
    except Exception as e:
        logger.error(f"Error initializing network activity DB for {username}: {e}")
    finally:
        conn.close()
    shared_folder = os.path.join(user_folder, "shared")
    os.makedirs(shared_folder, exist_ok=True)
    access_file = os.path.join(shared_folder, "file_access.txt")
    if not os.path.exists(access_file):
        with open(access_file, 'w') as f:
            f.write("read:True\nwrite:True\n")  # Default to enabled for testing
init_admin_db()
init_user_db()


# --- Anomaly Detection Functions ---
def detect_logon_anomaly(data):
    if not models.get('logon'):
        logger.warning("Logon anomaly model not loaded.")
        return None
    try:
        df = pd.DataFrame([data])
        df["date"] = pd.to_datetime(df["date"], errors='coerce')
        # Derive the same temporal/categorical features used in other models
        df["hour_of_day"] = df["date"].dt.hour
        df["day_of_week"] = df["date"].dt.dayofweek
        df["is_weekend"] = df["day_of_week"].apply(lambda x: 1 if x >= 5 else 0)
        df["is_midnight_activity"] = df["hour_of_day"].apply(lambda x: 1 if x < 5 else 0)
        df["time_since_last_activity"] = 0
        df["log_time_since_last_activity"] = np.log1p(df["time_since_last_activity"])
        df["activity_encoded"] = LabelEncoder().fit_transform(df["activity"])

        features = [
            "hour_of_day",
            "day_of_week",
            "is_weekend",
            "is_midnight_activity",
            "log_time_since_last_activity",
            "activity_encoded",
        ]
        X = df[features]
        prediction = models['logon'].predict(X)[0]
        return {"is_anomaly": prediction == -1}
    except Exception as e:
        logger.error(f"Logon anomaly detection error: {e}")
        return None

def detect_file_anomaly(data):
    if not models.get('file'):
        return None
    try:
        df = pd.DataFrame([data])
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df['activity_new'] = LabelEncoder().fit_transform(df['activity'])
        df['to_removable_media_new'] = LabelEncoder().fit_transform(df['to_removable_media'])
        df['from_removable_media_new'] = LabelEncoder().fit_transform(df['from_removable_media'])
        df['hour'] = df['date'].dt.hour
        features = df[['activity_new', 'to_removable_media_new', 'from_removable_media_new', 'hour']]
        prediction = models['file'].predict(features)[0]
        return {"is_anomaly": prediction == -1}
    except Exception as e:
        logger.error(f"File anomaly detection error: {e}")
        return None

def detect_http_anomaly(data):
    if not models.get('http'):
        return None
    try:
        df = pd.DataFrame([data])
        df['content_length'] = df['content'].apply(len)
        df['url_length'] = df['url'].apply(len)
        df['activity_encoded'] = LabelEncoder().fit_transform(df['activity'])
        features = df[['content_length', 'url_length', 'activity_encoded']]
        score = models['http'].decision_function(features)[0]
        prediction = models['http'].predict(features)[0]
        return {"score": score, "is_anomaly": prediction == -1}
    except Exception as e:
        logger.error(f"HTTP anomaly detection error: {e}")
        return None

def detect_device_anomaly(data):
    if not models.get('device'):
        return None
    try:
        df = pd.DataFrame([data])
        df["date"] = pd.to_datetime(df["date"])
        df["hour_of_day"] = df["date"].dt.hour
        df["day_of_week"] = df["date"].dt.dayofweek
        df["is_weekend"] = df["day_of_week"].apply(lambda x: 1 if x >= 5 else 0)
        df["is_midnight_activity"] = df["hour_of_day"].apply(lambda x: 1 if x < 5 else 0)
        df["time_since_last_activity"] = 0
        df["log_time_since_last_activity"] = np.log1p(df["time_since_last_activity"])
        df["activity_encoded"] = LabelEncoder().fit_transform(df["activity"])
        features = ["hour_of_day", "day_of_week", "is_weekend", "is_midnight_activity", "log_time_since_last_activity", "activity_encoded"]
        X = df[features]
        prediction = models['device'].predict(X)[0]
        return {"is_anomaly": prediction == -1}
    except Exception as e:
        logger.error(f"Device anomaly detection error: {e}")
        return None

def add_risk_score(user_id, anomaly_type):
    """Adds points to a user's risk score, persists the score, and emits an update."""
    if not user_id:
        logger.warning("Risk score update skipped: missing user_id.")
        return

    if user_id not in user_risk_scores:
        user_risk_scores[user_id] = 0

    points = ANOMALY_POINTS.get(anomaly_type, 5) # Default to 5 points
    user_risk_scores[user_id] += points
    new_score = user_risk_scores[user_id]

    # Persist the score so it survives Flask restarts and remains
    # consistent with the in-memory score shown on the dashboard.
    try:
        with sqlite3.connect("../users.db") as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_data SET risk_score = ? WHERE user_id = ?",
                (new_score, user_id)
            )
            if cursor.rowcount == 0:
                logger.warning(f"Risk score not persisted: user {user_id} not found in database.")
            conn.commit()
    except Exception as e:
        logger.error(f"Error persisting risk score for {user_id}: {e}")

    socketio.emit('update_risk_score', {
        'user_id': user_id, 
        'score': new_score
    })


# Utility Functions
def get_user_folder(username):
    # Get the project root directory (parent of frontend)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    user_folder = os.path.join(project_root, "users", username)
    os.makedirs(user_folder, exist_ok=True)
    os.makedirs(os.path.join(user_folder, "photos"), exist_ok=True)
    os.makedirs(os.path.join(user_folder, "screenshots"), exist_ok=True)
    return user_folder

def log_anomaly(anomaly_type, user_id, username, details, severity="medium"):
    """Log anomaly to persistent logs with 24-hour retention"""
    try:
        timestamp = datetime.now().isoformat()
        log_entry = {
            "timestamp": timestamp,
            "type": anomaly_type,
            "user_id": user_id,
            "username": username,
            "details": details,
            "severity": severity
        }
        
        # Log to specific anomaly type file
        log_file = f"logs/anomaly_{anomaly_type}.log"
        with open(log_file, 'a') as f:
            f.write(json.dumps(log_entry) + "\n")
        
        # Log to general anomaly log
        with open("logs/anomaly_all.log", 'a') as f:
            f.write(json.dumps(log_entry) + "\n")
        
        # Log to admin alerts (existing functionality)
        alert_msg = f"{timestamp} - {anomaly_type.upper()} ANOMALY: {details}"
        _append_line('users/admin/anomaly_alerts.txt', alert_msg)
        
        logger.info(f"Anomaly logged: {anomaly_type} for {username}")
        
    except Exception as e:
        logger.error(f"Error logging anomaly: {e}")


def get_anomaly_logs(hours=24):
    """Get anomaly logs from the last N hours"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=hours)
        all_anomalies = []
        
        # Read from general anomaly log
        if os.path.exists("logs/anomaly_all.log"):
            with open("logs/anomaly_all.log", 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry['timestamp'])
                        if entry_time >= cutoff_time:
                            all_anomalies.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue
        
        # Sort by timestamp (newest first)
        all_anomalies.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return all_anomalies
        
    except Exception as e:
        logger.error(f"Error getting anomaly logs: {e}")
        return []


def cleanup_old_logs():
    """Clean up logs older than 24 hours"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=24)
        
        # Clean up general anomaly log
        if os.path.exists("logs/anomaly_all.log"):
            temp_lines = []
            with open("logs/anomaly_all.log", 'r') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        entry_time = datetime.fromisoformat(entry['timestamp'])
                        if entry_time >= cutoff_time:
                            temp_lines.append(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
            
            with open("logs/anomaly_all.log", 'w') as f:
                f.writelines(temp_lines)
        
        # Clean up specific anomaly logs
        for log_type in ['logon', 'file', 'http', 'device']:
            log_file = f"logs/anomaly_{log_type}.log"
            if os.path.exists(log_file):
                temp_lines = []
                with open(log_file, 'r') as f:
                    for line in f:
                        try:
                            entry = json.loads(line.strip())
                            entry_time = datetime.fromisoformat(entry['timestamp'])
                            if entry_time >= cutoff_time:
                                temp_lines.append(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                
                with open(log_file, 'w') as f:
                    f.writelines(temp_lines)
        
        logger.info("Cleaned up old anomaly logs")
        
    except Exception as e:
        logger.error(f"Error cleaning up logs: {e}")
        
threading.Thread(target=cleanup_logs_periodically, daemon=True).start()

def _append_line(filepath: str, line: str) -> None:
    try:
        with open(filepath, 'a') as f:
            f.write(line + "\n")
    except Exception as e:
        logger.error(f"Error writing to {filepath}: {e}")


def log_user_activity(username, message, logs=None):
    try:
        timestamp = datetime.now().isoformat()
        user_folder = get_user_folder(username)
        # Persist to admin consolidated activity log
        _append_line('users/admin/admin_activity.log', f"{timestamp} - USER:{username} - {message}")

        # Also persist into users.db 'logs' JSON array (prepend, cap at 200)
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT logs FROM user_data WHERE username = ?", (username,))
        row = c.fetchone()
        log_arr = []
        if row and row[0]:
            try:
                log_arr = json.loads(row[0])
            except Exception:
                log_arr = []
        log_arr.insert(0, {"time": timestamp, "message": message})
        log_arr = log_arr[:200]
        c.execute("UPDATE user_data SET logs = ? WHERE username = ?", (json.dumps(log_arr), username))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error in log_user_activity: {e}")

def log_admin_activity(action):
    try:
        timestamp = datetime.now().isoformat()
        _append_line('users/admin/admin_activity.log', f"{timestamp} - ADMIN - {action}")
    except Exception as e:
        logger.error(f"Error in log_admin_activity: {e}")


def log_file_access(username: str, action: str, details: dict) -> None:
    try:
        timestamp = datetime.now().isoformat()
        user_folder = get_user_folder(username)
        per_user_log = os.path.join(user_folder, "shared", "file_access.log")
        os.makedirs(os.path.dirname(per_user_log), exist_ok=True)
        line = f"{timestamp} - USER:{username} - ACTION:{action} - DETAILS:{json.dumps(details, ensure_ascii=False)}"
        _append_line(per_user_log, line)
        _append_line('users/admin/file_access_logs.txt', line)
    except Exception as e:
        logger.error(f"Error in log_file_access: {e}")

def get_all_users():
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT user_id, username, pc_name, platform, accepted FROM user_data")
        return c.fetchall()
    except Exception as e:
        logger.error(f"Error getting users: {e}")
        return []
    finally:
        conn.close()

# --- Main Route (Updated to pass risk scores to template) ---
@app.route("/")
def dashboard():
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))
    
    # Load anomaly logs for the last 24 hours
    anomaly_logs = get_anomaly_logs(24)
    
    # NEW: Pass the current risk scores and anomaly logs to the dashboard
    return render_template(
        "dashboard.html", 
        users=get_all_users(), 
        online_user_ids=list(online_users.keys()),
        risk_scores=json.dumps(user_risk_scores),
        anomaly_logs=json.dumps(anomaly_logs)
    )

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        try:
            conn = sqlite3.connect("admin.db")
            c = conn.cursor()
            c.execute("SELECT password FROM admin_password WHERE id = 1")
            result = c.fetchone()
            if result and result[0] == password and username == "admin":
                session['admin_logged_in'] = True
                log_admin_activity("Admin logged in")
                return redirect(url_for('dashboard'))
        except Exception as e:
            logger.error(f"Login error: {e}")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    if 'admin_logged_in' in session:
        log_admin_activity("Admin logged out")
    session.pop('admin_logged_in', None)
    return redirect(url_for('login'))


# --- Anomaly Reporting Routes (Updated to call add_risk_score) ---
@app.route("/report_logon_activity", methods=["POST"])
def report_logon_activity():
    data = request.json
    username = data.get("user")
    user_id = data.get("user_id")
    anomaly_result = detect_logon_anomaly(data)
    
    if anomaly_result and anomaly_result["is_anomaly"]:
        add_risk_score(user_id, 'logon') # NEW
        alert_msg = f"Suspicious logon behavior detected for {username}"
        socketio.emit("logon_anomaly_alert", {"message": alert_msg, "user_id": user_id})
        log_user_activity(username, f"LOGON ANOMALY: {alert_msg}")
        
        # Log to persistent anomaly logs
        log_anomaly("logon", user_id, username, alert_msg, "high")
        
    return jsonify({"status": "processed"})

@app.route("/report_file_activity", methods=["POST"])
def report_file_activity():
    data = request.json
    username = data.get("user")
    user_id = data.get("user_id")
    anomaly_result = detect_file_anomaly(data)
    
    if anomaly_result and anomaly_result["is_anomaly"]:
        add_risk_score(user_id, 'file') # NEW
        alert_msg = f"Suspicious file activity detected for {username}: {data.get('activity')} on {data.get('filename')}"
        socketio.emit("file_anomaly_alert", {"message": alert_msg, "user_id": user_id})
        log_user_activity(username, f"FILE ANOMALY: {alert_msg}")
        
        # Log to persistent anomaly logs
        log_anomaly("file", user_id, username, alert_msg, "high")
        
    return jsonify({"status": "processed"})

@app.route("/report_http_activity", methods=["POST"])
def report_http_activity():
    data = request.json
    username = data.get("user")
    user_id = data.get("user_id")
    anomaly_result = detect_http_anomaly(data)

    if anomaly_result and anomaly_result["is_anomaly"]:
        add_risk_score(user_id, 'http') # NEW
        alert_msg = f"Suspicious HTTP activity detected for {username} (URL: {data.get('url')[:30]}...)"
        socketio.emit("http_anomaly_alert", {"message": alert_msg, "user_id": user_id, "score": anomaly_result.get('score', 0)})
        log_user_activity(username, f"HTTP ANOMALY: {alert_msg}")
        
        # Log to persistent anomaly logs
        log_anomaly("http", user_id, username, alert_msg, "medium")

    return jsonify({"status": "processed"})

@app.route("/usb_event", methods=["POST"])
def usb_event():
    try:
        data = request.json
        username = data.get("username")
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT user_id, removable_media_transfers FROM user_data WHERE username = ?", (username,))
        result = c.fetchone()
        if not result:
            return jsonify({"error": "User not found"}), 404
        user_id = result[0]
        current_transfers = json.loads(result[1]) if result[1] else []

        operation = data.get("operation")
        device_data = {"date": data.get("timestamp"), "user": username, "activity": operation}
        anomaly_result = detect_device_anomaly(device_data)

        # Add the new USB event to the user's log
        transfer_entry = {
            "operation": operation,
            "device_info": data.get("device_info"),
            "timestamp": data.get("timestamp"),
            "details": data.get("details", {})
        }
        current_transfers.insert(0, transfer_entry)
        
        c.execute("UPDATE user_data SET usb_count = usb_count + 1, removable_media_transfers = ? WHERE user_id = ?", (json.dumps(current_transfers), user_id))
        conn.commit()
        
        alert_msg = f"{datetime.now().isoformat()} - USB Event: {operation} by {username}"
        
        if "Inserted" in operation:
            add_risk_score(user_id, 'device')
            alert_msg = f"ANOMALY: Suspicious device connection for {username}"
            socketio.emit("device_anomaly_alert", {"message": alert_msg, "user_id": user_id})
            
            # Log to persistent anomaly logs
            log_anomaly("device", user_id, username, alert_msg, "high")
        
        elif "Removed" in operation:
            alert_msg = f"USB removed by {username}"
            socketio.emit("usb_alert", {"message": alert_msg, "user_id": user_id})
            with open('users/admin/usb_alerts.txt', 'a') as f:
                f.write(alert_msg + "\n")
        
        elif "File Copied" in operation:
            add_risk_score(user_id, 'usb_file_copy')
            file_details = data.get("details", {})
            file_name = file_details.get("filename", "N/A")
            direction = file_details.get("direction", "N/A")
            from_loc = file_details.get("from_location", "N/A")
            to_loc = file_details.get("to_location", "N/A")
            
            alert_msg = f"ANOMALY: File '{file_name}' transferred from '{from_loc}' to '{to_loc}' ({direction.upper()})"
            socketio.emit("device_anomaly_alert", {"message": alert_msg, "user_id": user_id})
            with open('users/admin/anomaly_alerts.txt', 'a') as f:
                f.write(f"{datetime.now().isoformat()} - {alert_msg}\n")

        return jsonify({"status": "logged"})

    except Exception as e:
        logger.error(f"Error logging USB event: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()



@app.route("/report_location/<user_id>", methods=["POST"])
def report_location(user_id):
    try:
        data = request.json
        location = data.get("location")
        username = data.get("username")
        
        if not location:
            return jsonify({"error": "No location data"}), 400
            
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        
        # Get current locations
        c.execute("SELECT locations FROM user_data WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        current_locations = json.loads(result[0]) if result and result[0] else []
        
        # Add new location (limit to last 50)
        current_locations.insert(0, location)
        current_locations = current_locations[:50]
        
        # Update database
        c.execute("""
            UPDATE user_data 
            SET locations = ? 
            WHERE user_id = ?
        """, (json.dumps(current_locations), user_id))
        conn.commit()
        
        log_user_activity(username, f"Location updated: {location}")
        return jsonify({"status": "location_updated"})
    except Exception as e:
        logger.error(f"Error updating location: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/clear_usb_alerts", methods=["POST"])
def clear_usb_alerts():
    try:
        with open('users/admin/usb_alerts.txt', 'w') as f:
            f.write("")
        return jsonify({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing USB alerts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/clear_anomaly_alerts", methods=["POST"])
def clear_anomaly_alerts():
    try:
        with open('users/admin/anomaly_alerts.txt', 'w') as f:
            f.write("")
        return jsonify({"status": "cleared"})
    except Exception as e:
        logger.error(f"Error clearing anomaly alerts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/get_usb_alerts", methods=["GET"])
def get_usb_alerts():
    try:
        with open('users/admin/usb_alerts.txt', 'r') as f:
            alerts = [line.strip() for line in f.readlines() if line.strip()]
        return jsonify({"alerts": alerts[-50:]})  # Last 50 alerts
    except Exception as e:
        logger.error(f"Error getting USB alerts: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/get_anomaly_logs", methods=["GET"])
def get_anomaly_logs_route():
    """Get anomaly logs for the last 24 hours"""
    try:
        hours = request.args.get('hours', 24, type=int)
        logs = get_anomaly_logs(hours)
        return jsonify({"anomalies": logs, "count": len(logs)})
    except Exception as e:
        logger.error(f"Error getting anomaly logs: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/get_packet_data/<user_id>", methods=["GET"])
def get_packet_data(user_id):
    """Get packet analysis data for a user"""
    try:
        with sqlite3.connect("../users.db") as conn:
            c = conn.cursor()
            c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
            result = c.fetchone()
            if not result:
                return jsonify({"error": "User not found"}), 404
            
            username = result[0]
            user_folder = get_user_folder(username)
            network_activity_db = os.path.join(user_folder, "network_activity.db")
            
            packet_analysis = []
            
            if os.path.exists(network_activity_db):
                with sqlite3.connect(network_activity_db) as conn_network:
                    c_network = conn_network.cursor()
                    
                    # Get packet analysis - only most recent entry per interface (excluding loopback)
                    try:
                        c_network.execute("""
                            SELECT interface, remote_ip, bytes_sent, bytes_recv, bytes_sent_rate, bytes_recv_rate,
                                   packets_sent, packets_recv, packets_sent_rate, packets_recv_rate,
                                   errors_in, errors_out, drops_in, drops_out, connection_count, 
                                   ports, protocols, processes, total_bytes_sent, total_bytes_recv, timestamp
                            FROM packet_analysis
                            WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                            AND id IN (
                                SELECT MAX(id)
                                FROM packet_analysis
                                WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                                GROUP BY interface
                            )
                            ORDER BY timestamp DESC
                            LIMIT 20
                        """)
                        packet_analysis = [{
                            "interface": row[0],
                            "remote_ip": row[1],
                            "bytes_sent": row[2],
                            "bytes_recv": row[3],
                            "bytes_sent_rate": row[4],
                            "bytes_recv_rate": row[5],
                            "packets_sent": row[6],
                            "packets_recv": row[7],
                            "packets_sent_rate": row[8],
                            "packets_recv_rate": row[9],
                            "errors_in": row[10],
                            "errors_out": row[11],
                            "drops_in": row[12],
                            "drops_out": row[13],
                            "connection_count": row[14],
                            "ports": json.loads(row[15]) if row[15] else [],
                            "protocols": json.loads(row[16]) if row[16] else [],
                            "processes": json.loads(row[17]) if row[17] else [],
                            "total_bytes_sent": row[18],
                            "total_bytes_recv": row[19],
                            "timestamp": row[20]
                        } for row in c_network.fetchall()]
                    except sqlite3.OperationalError:
                        # Fallback to old schema
                        c_network.execute("""
                            SELECT interface, remote_ip, bytes_sent, bytes_recv, packets_sent, packets_recv,
                                   errors_in, errors_out, drops_in, drops_out, connection_count, ports, protocols, timestamp
                            FROM packet_analysis
                            ORDER BY timestamp DESC
                            LIMIT 100
                        """)
                        packet_analysis = [{
                            "interface": row[0],
                            "remote_ip": row[1],
                            "bytes_sent": row[2],
                            "bytes_recv": row[3],
                            "bytes_sent_rate": 0.0,
                            "bytes_recv_rate": 0.0,
                            "packets_sent": row[4],
                            "packets_recv": row[5],
                            "packets_sent_rate": 0.0,
                            "packets_recv_rate": 0.0,
                            "errors_in": row[6],
                            "errors_out": row[7],
                            "drops_in": row[8],
                            "drops_out": row[9],
                            "connection_count": row[10],
                            "ports": json.loads(row[11]) if row[11] else [],
                            "protocols": json.loads(row[12]) if row[12] else [],
                            "processes": [],
                            "total_bytes_sent": row[2],
                            "total_bytes_recv": row[3],
                            "timestamp": row[13]
                        } for row in c_network.fetchall()]
            
            return jsonify({
                "packet_analysis": packet_analysis
            })
    except Exception as e:
        logger.error(f"Error getting packet data: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/validate_user_password", methods=["POST"])
def validate_user_password():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")
        
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT password FROM user_data WHERE username = ?", (username,))
        result = c.fetchone()
        
        if result and result[0] == password:
            return jsonify({"status": "valid"})
        return jsonify({"status": "invalid"})
    except Exception as e:
        logger.error(f"Password validation error: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/get_user_id/<username>", methods=["GET"])
def get_user_id(username):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT user_id FROM user_data WHERE username = ?", (username,))
        result = c.fetchone()
        
        if result:
            return jsonify({"user_id": result[0]})
        return jsonify({"error": "User not found"}), 404
    except Exception as e:
        logger.error(f"Error getting user ID: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/add_user", methods=["POST"])
def add_user():
    data = request.json
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute(
            "INSERT INTO user_data (user_id, username, password, pc_name, platform) VALUES (?, ?, ?, ?, ?)",
            (data["user_id"], data["username"], data["password"], data["pc_name"], data["platform"])
        )
        conn.commit()
        
        # Initialize user-specific databases
        init_user_databases(data["username"])
        
        socketio.emit("new_user", {
            "user_id": data["user_id"],
            "username": data["username"],
            "pc_name": data["pc_name"],
            "platform": data["platform"]
        })
        
        log_admin_activity(f"Added new user: {data['username']}")
        log_user_activity(data["username"], "New user added")
        return jsonify({"status": "user_added"})
    except Exception as e:
        logger.error(f"Error adding user: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/accept_user/<user_id>", methods=["POST"])
def accept_user(user_id):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        c.execute("UPDATE user_data SET accepted = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        
        log_admin_activity(f"Accepted user {user[0]} (ID: {user_id})")
        socketio.emit("user_accepted", {"user_id": user_id})
        log_user_activity(user[0], "User accepted by admin")
        return jsonify({"status": "user_accepted"})
    except Exception as e:
        logger.error(f"Error accepting user: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/remove_user/<user_id>", methods=["POST"])
def remove_user(user_id):
    if 'admin_logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    admin_password = data.get("admin_password")
    
    try:
        # Verify admin password
        conn = sqlite3.connect("admin.db")
        c = conn.cursor()
        c.execute("SELECT password FROM admin_password WHERE id = 1")
        result = c.fetchone()
        
        if not result or result[0] != admin_password:
            return jsonify({"error": "Incorrect admin password"}), 401

        # Get username before deleting for logging
        conn_user = sqlite3.connect("../users.db")
        c_user = conn_user.cursor()
        c_user.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        user = c_user.fetchone()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        username = user[0]

        # Delete user from main database
        c_user.execute("DELETE FROM user_data WHERE user_id = ?", (user_id,))
        conn_user.commit()
        
        # Remove user folder (which contains all user-specific databases)
        user_folder = os.path.join("users", username)
        if os.path.exists(user_folder):
            shutil.rmtree(user_folder)
        
        log_admin_activity(f"Removed user {username} (ID: {user_id})")
        socketio.emit("user_removed", {"user_id": user_id})
        
        return jsonify({"status": "user_removed"})
    except Exception as e:
        logger.error(f"Error removing user: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
     if 'conn' in locals():
        conn.close()
     if 'conn_user' in locals():
        conn_user.close()

@app.route("/logout_user/<user_id>", methods=["POST"])
def logout_user(user_id):
    if 'admin_logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        
        # Get username and login_time for logging
        c.execute("SELECT username, login_time FROM user_data WHERE user_id = ?", (user_id,))
        user_data = c.fetchone()
        if not user_data:
            return jsonify({"error": "User not found"}), 404
        
        username = user_data[0]
        login_time_str = user_data[1]
        
        # Calculate login duration
        login_duration_sec = 0
        if login_time_str:
            login_time_dt = datetime.fromisoformat(login_time_str)
            login_duration_sec = int((datetime.now() - login_time_dt).total_seconds())

        # Update logout time and login duration
        c.execute("""
            UPDATE user_data SET 
                logout_time = ?,
                login_duration = ?
            WHERE user_id = ?
        """, (
            datetime.now().isoformat(),
            login_duration_sec,
            user_id
        ))
        conn.commit()
        
        log_admin_activity(f"Logged out user {username} (ID: {user_id})")
        
        # Emit logout event to specific user's client using their session ID
        client_sid = client_sids.get(user_id)
        if client_sid:
            socketio.emit("user_logged_out", {"user_id": user_id}, to=client_sid)
            logger.info(f"Sent logout command to user {username} (ID: {user_id}, SID: {client_sid})")
        else:
            logger.warning(f"User {username} (ID: {user_id}) not connected via SocketIO, logout event not sent")
        
        # Clean up user tracking
        if user_id in online_users:
            del online_users[user_id]
        if user_id in client_sids:
            del client_sids[user_id]
        
        return jsonify({"status": "user_logged_out"})
    except Exception as e:
        logger.error(f"Error logging out user: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/clear_risk_score/<user_id>", methods=["POST"])
def clear_risk_score(user_id):
    if 'admin_logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        user_risk_scores[user_id] = 0
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("UPDATE user_data SET risk_score = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        socketio.emit('update_risk_score', {'user_id': user_id, 'score': 0})
        log_admin_activity(f"Cleared risk score for user ID: {user_id}")
        return jsonify({"status": "score_cleared"})
    except Exception as e:
        logger.error(f"Error clearing risk score: {e}")
        return jsonify({"error": str(e)}), 500
    


@app.route("/user_details/<user_id>", methods=["GET"])
def user_details(user_id):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("""
            SELECT user_id, username, password, pc_name, platform, accepted, 
                   logs, network_traffic, file_operations, removable_media_transfers, 
                   user_activity, login_time, logout_time, login_duration, 
                   internet_status, usb_count, system_info, locations, risk_score
            FROM user_data 
            WHERE user_id = ?
        """, (user_id,))
        data = c.fetchone()

        if not data:
            return jsonify({"error": "User not found"}), 404

        return jsonify({
            "user_id": data[0],
            "username": data[1],
            "pc_name": data[3],
            "logs": data[6] if data[6] else "[]",
            "network_traffic": data[7] if data[7] else "{}",
            "file_operations": data[8] if data[8] else "[]",
            "removable_media_transfers": data[9] if data[9] else "[]",
            "user_activity": data[10] if data[10] else "[]",
            "login_time": data[11],
            "logout_time": data[12],
            "login_duration": data[13],
            "internet_status": data[14],
            "usb_count": data[15],
            "system_info": data[16] if data[16] else "{}",
            "locations": data[17] if data[17] else "[]",
            "accepted": data[5],
            "risk_score": data[18]
        })
    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/report_web_activity/<user_id>", methods=["POST"])
def report_web_activity(user_id):
    try:
        data = request.json
        username = data.get("username")
        
        user_folder = get_user_folder(username)
        web_activity_db = os.path.join(user_folder, "web_activity.db")
        online_data_db = os.path.join(user_folder, "online_data.db")
        
        with sqlite3.connect(web_activity_db) as conn_web:
            c_web = conn_web.cursor()
            for activity in data.get("visited_sites", []):
                c_web.execute("""
                    INSERT INTO web_activity (url, title, visit_time, duration)
                    VALUES (?, ?, ?, ?)
                """, (
                    activity.get("url"), 
                    activity.get("title", ""), 
                    activity.get("time", ""), 
                    activity.get("duration", "")
                ))
        
        with sqlite3.connect(online_data_db) as conn_online:
            c_online = conn_online.cursor()
            for download in data.get("downloaded_files", []):
                file_path = download.get("path", "")
                filename = download.get("filename", "")
                timestamp = download.get("timestamp", "")
                
                # Check if this download already exists (based on path and timestamp)
                c_online.execute("""
                    SELECT COUNT(*) FROM file_downloads 
                    WHERE url = ? AND filename = ? AND timestamp = ?
                """, (file_path, filename, timestamp))
                
                if c_online.fetchone()[0] == 0:
                    # Only insert if it doesn't already exist
                    c_online.execute("""
                        INSERT INTO file_downloads (url, filename, timestamp, size)
                        VALUES (?, ?, ?, ?)
                    """, (
                        file_path, 
                        filename,
                        timestamp,
                        download.get("size", "N/A")
                    ))
            conn_online.commit()

        log_user_activity(username, "Web and download activity reported")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error processing web activity: {e}")
        return jsonify({"error": str(e)}), 500
    

@app.route("/report_network_activity/<user_id>", methods=["POST"])
def report_network_activity(user_id):
    try:
        data = request.json
        username = data.get("username")
        
        user_folder = get_user_folder(username)
        network_activity_db = os.path.join(user_folder, "network_activity.db")
        conn = sqlite3.connect(network_activity_db)
        c = conn.cursor()
        
        for activity in data.get("network_activity", []):
            c.execute("""
                INSERT INTO network_activity (
                    protocol, remote_ip, port, status, pid, 
                    interface, sent_bytes, received_bytes, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                activity.get("protocol", "TCP"),
                activity.get("remote_ip", ""),
                activity.get("port", 0),
                activity.get("status", ""),
                activity.get("pid", 0),
                activity.get("interface", ""),
                activity.get("sent_bytes", 0),
                activity.get("received_bytes", 0),
                datetime.now().isoformat()
            ))
        
        conn.commit()
        
        log_user_activity(username, "Network activity reported")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error processing network activity: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/report_packet_analysis/<user_id>", methods=["POST"])
def report_packet_analysis(user_id):
    try:
        data = request.json
        username = data.get("username")
        
        user_folder = get_user_folder(username)
        network_activity_db = os.path.join(user_folder, "network_activity.db")
        conn = sqlite3.connect(network_activity_db)
        c = conn.cursor()
        
        for packet in data.get("packets", []):
            c.execute("""
                INSERT INTO packet_analysis (
                    interface, remote_ip, bytes_sent, bytes_recv, bytes_sent_rate, bytes_recv_rate,
                    packets_sent, packets_recv, packets_sent_rate, packets_recv_rate,
                    errors_in, errors_out, drops_in, drops_out, connection_count, 
                    ports, protocols, processes, total_bytes_sent, total_bytes_recv, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                packet.get("interface", ""),
                packet.get("remote_ip", ""),
                packet.get("bytes_sent", 0),
                packet.get("bytes_recv", 0),
                packet.get("bytes_sent_rate", 0.0),
                packet.get("bytes_recv_rate", 0.0),
                packet.get("packets_sent", 0),
                packet.get("packets_recv", 0),
                packet.get("packets_sent_rate", 0.0),
                packet.get("packets_recv_rate", 0.0),
                packet.get("errors_in", 0),
                packet.get("errors_out", 0),
                packet.get("drops_in", 0),
                packet.get("drops_out", 0),
                packet.get("connection_count", 0),
                json.dumps(packet.get("ports", [])),
                json.dumps(packet.get("protocols", [])),
                json.dumps(packet.get("processes", [])),
                packet.get("total_bytes_sent", 0),
                packet.get("total_bytes_recv", 0),
                packet.get("timestamp", datetime.now().isoformat())
            ))
        
        conn.commit()
        log_user_activity(username, f"Packet analysis reported: {len(data.get('packets', []))} entries")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error processing packet analysis: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/user_logs/<user_id>")
def user_logs(user_id):
    try:
        user_data = None
        visits = []
        downloads = []
        web_activity = []
        network_activity = []
        system_info = {}
        locations = []
        removable_media_transfers = []

        with sqlite3.connect("../users.db") as conn:
            c = conn.cursor()
            c.execute("""
                SELECT user_id, username, password, pc_name, platform, accepted, 
                       logs, network_traffic, file_operations, removable_media_transfers, 
                       user_activity, login_time, logout_time, login_duration, 
                       internet_status, usb_count, system_info, locations
                FROM user_data 
                WHERE user_id = ?
            """, (user_id,))
            user_data = c.fetchone()

            if not user_data:
                return "User not found", 404

            is_online = user_id in online_users
            internet_status = "online" if is_online else "offline"

            username = user_data[1]
            user_folder = get_user_folder(username)

            online_data_db = os.path.join(user_folder, "online_data.db")
            if os.path.exists(online_data_db):
                with sqlite3.connect(online_data_db) as conn_online:
                    c_online = conn_online.cursor()
                    c_online.execute("""
                        SELECT url, title, timestamp 
                        FROM website_visits 
                        ORDER BY timestamp DESC 
                        LIMIT 100
                    """)
                    visits = [{"url": row[0], "title": row[1], "timestamp": row[2]} 
                            for row in c_online.fetchall()]
                    
                    # Get unique downloads (deduplicate by path and filename, keeping the most recent)
                    c_online.execute("""
                        SELECT url, filename, timestamp, size
                        FROM file_downloads 
                        WHERE id IN (
                            SELECT MAX(id) 
                            FROM file_downloads 
                            GROUP BY url, filename
                        )
                        ORDER BY timestamp DESC 
                        LIMIT 100
                    """)
                    downloads = [{"url": row[0], "filename": row[1], "timestamp": row[2], "size": row[3]} 
                                for row in c_online.fetchall()]
            
            web_activity_db = os.path.join(user_folder, "web_activity.db")
            if os.path.exists(web_activity_db):
                with sqlite3.connect(web_activity_db) as conn_web:
                    c_web = conn_web.cursor()
                    c_web.execute("""
                        SELECT url, title, visit_time, duration 
                        FROM web_activity 
                        ORDER BY visit_time DESC 
                        LIMIT 100
                    """)
                    web_activity = [{
                        "url": row[0],
                        "title": row[1],
                        "time": row[2],
                        "duration": row[3]
                    } for row in c_web.fetchall()]
            
            network_activity_db = os.path.join(user_folder, "network_activity.db")
            if os.path.exists(network_activity_db):
                with sqlite3.connect(network_activity_db) as conn_network:
                    c_network = conn_network.cursor()
                    c_network.execute("""
                        SELECT protocol, remote_ip, port, status, sent_bytes, received_bytes, timestamp
                        FROM network_activity
                        ORDER BY timestamp DESC
                        LIMIT 100
                    """)
                    network_activity = [{
                        "protocol": row[0],
                        "remote_ip": row[1],
                        "port": row[2],
                        "status": row[3],
                        "sent_bytes": row[4],
                        "received_bytes": row[5],
                        "timestamp": row[6]
                    } for row in c_network.fetchall()]
                    
                    # Get packet analysis - only most recent entry per interface (excluding loopback)
                    try:
                        c_network.execute("""
                            SELECT interface, remote_ip, bytes_sent, bytes_recv, bytes_sent_rate, bytes_recv_rate,
                                   packets_sent, packets_recv, packets_sent_rate, packets_recv_rate,
                                   errors_in, errors_out, drops_in, drops_out, connection_count, 
                                   ports, protocols, processes, total_bytes_sent, total_bytes_recv, timestamp
                            FROM packet_analysis
                            WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                            AND id IN (
                                SELECT MAX(id)
                                FROM packet_analysis
                                WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                                GROUP BY interface
                            )
                            ORDER BY timestamp DESC
                            LIMIT 20
                        """)
                        packet_analysis = [{
                            "interface": row[0],
                            "remote_ip": row[1],
                            "bytes_sent": row[2],
                            "bytes_recv": row[3],
                            "bytes_sent_rate": row[4],
                            "bytes_recv_rate": row[5],
                            "packets_sent": row[6],
                            "packets_recv": row[7],
                            "packets_sent_rate": row[8],
                            "packets_recv_rate": row[9],
                            "errors_in": row[10],
                            "errors_out": row[11],
                            "drops_in": row[12],
                            "drops_out": row[13],
                            "connection_count": row[14],
                            "ports": json.loads(row[15]) if row[15] else [],
                            "protocols": json.loads(row[16]) if row[16] else [],
                            "processes": json.loads(row[17]) if row[17] else [],
                            "total_bytes_sent": row[18],
                            "total_bytes_recv": row[19],
                            "timestamp": row[20]
                        } for row in c_network.fetchall()]
                    except sqlite3.OperationalError:
                        # Fallback to old schema
                        c_network.execute("""
                            SELECT interface, remote_ip, bytes_sent, bytes_recv, packets_sent, packets_recv,
                                   errors_in, errors_out, drops_in, drops_out, connection_count, ports, protocols, timestamp
                            FROM packet_analysis
                            WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                            AND id IN (
                                SELECT MAX(id)
                                FROM packet_analysis
                                WHERE interface IS NOT NULL AND interface != '' AND interface != 'lo'
                                GROUP BY interface
                            )
                            ORDER BY timestamp DESC
                            LIMIT 20
                        """)
                        packet_analysis = [{
                            "interface": row[0],
                            "remote_ip": row[1],
                            "bytes_sent": row[2],
                            "bytes_recv": row[3],
                            "bytes_sent_rate": 0.0,
                            "bytes_recv_rate": 0.0,
                            "packets_sent": row[4],
                            "packets_recv": row[5],
                            "packets_sent_rate": 0.0,
                            "packets_recv_rate": 0.0,
                            "errors_in": row[6],
                            "errors_out": row[7],
                            "drops_in": row[8],
                            "drops_out": row[9],
                            "connection_count": row[10],
                            "ports": json.loads(row[11]) if row[11] else [],
                            "protocols": json.loads(row[12]) if row[12] else [],
                            "processes": [],
                            "total_bytes_sent": row[2],
                            "total_bytes_recv": row[3],
                            "timestamp": row[13]
                        } for row in c_network.fetchall()]
            else:
                email_activity = []
                packet_analysis = []

            system_info = json.loads(user_data[16]) if user_data[16] else {}
            locations = json.loads(user_data[17]) if user_data[17] else []
            removable_media_transfers = json.loads(user_data[9]) if user_data[9] else []

            # Convert login duration seconds to a readable format
            duration_sec = user_data[13] if user_data[13] is not None else 0
            if duration_sec > 0:
                hours, remainder = divmod(duration_sec, 3600)
                minutes, seconds = divmod(remainder, 60)
                login_duration_str = f"{int(hours)}h {int(minutes)}m {int(seconds)}s"
            else:
                login_duration_str = "0h 0m 0s"
            
            return render_template("user_logs.html",
                user_id=user_id,
                pc_name=user_data[3],
                logs=json.loads(user_data[6]) if user_data[6] else [],
                network_traffic=json.loads(user_data[7]) if user_data[7] else {},
                file_operations=json.loads(user_data[8]) if user_data[8] else [],
                removable_media_transfers=removable_media_transfers,
                user_activity=json.loads(user_data[10]) if user_data[10] else [],
                login_time=user_data[11] if user_data[11] else "N/A",
                logout_time=user_data[12] if user_data[12] else "N/A",
                login_duration=login_duration_str,
                internet_status=internet_status,
                usb_count=user_data[15] if user_data[15] else 0,
                website_visits=visits,
                downloaded_files=downloads,
                web_activity=web_activity,
                network_activity=network_activity,
                packet_analysis=packet_analysis,
                system_info=system_info,
                locations=locations,
                last_update=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
            
    except Exception as e:
        logger.error(f"Error loading user logs: {str(e)}")
        return render_template("error.html", 
                             error_message=f"Error loading logs: {str(e)}",
                             user_id=user_id)

@app.route("/update_activity/<user_id>", methods=["POST"])
def update_activity(user_id):
    try:
        data = request.json
        
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username, usb_count FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        
        if not user:
            return jsonify({"error": "User not found"}), 404
            
        username = user[0]

        # Calculate duration if login_time and logout_time are provided
        login_time_str = data.get("login_time")
        logout_time_str = data.get("logout_time")
        login_duration_sec = 0
        if login_time_str and logout_time_str:
            login_time_dt = datetime.fromisoformat(login_time_str)
            logout_time_dt = datetime.fromisoformat(logout_time_str)
            login_duration_sec = int((logout_time_dt - login_time_dt).total_seconds())

        c.execute("""
            UPDATE user_data SET
                logs = ?,
                network_traffic = ?,
                login_time = ?,
                logout_time = ?,
                system_info = ?,
                usb_count = ?,
                login_duration = ?,
                risk_score = ?
            WHERE user_id = ?
        """, (
            data.get("logs", "[]"),
            data.get("network_traffic", "{}"),
            login_time_str,
            logout_time_str,
            data.get("system_info", "{}"),
            data.get("usb_count", 0),
            login_duration_sec,
            user_risk_scores.get(user_id, 0),
            user_id
        ))
        conn.commit()
        
        socketio.emit("update_logs", {
            "user_id": user_id,
            "logs": json.loads(data.get("logs", "[]")),
            "network_traffic": json.loads(data.get("network_traffic", "{}"))
        })
        
        return jsonify({"status": "updated"})
    
    except Exception as e:
        logger.error(f"Error updating activity: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/webcam/<user_id>")
def webcam(user_id):
    if 'admin_logged_in' not in session:
        return redirect(url_for('login'))
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username, pc_name FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if not user: return "User not found", 404
        return render_template("webcam.html", user_id=user_id, username=user[0], pc_name=user[1])
    except Exception as e:
        logger.error(f"Error loading webcam page: {e}")
        return "Error loading page", 500
    finally:
        conn.close()


@app.route("/get_user_media/<media_type>/<user_id>", methods=["GET"])
def get_user_media(media_type, user_id):
    if 'admin_logged_in' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if not user: return jsonify({"error": "User not found"}), 404
        
        username = user[0]
        media_folder = os.path.join(get_user_folder(username), media_type)
        if not os.path.exists(media_folder):
            return jsonify({"files": []})
        
        files = sorted(os.listdir(media_folder), reverse=True)
        return jsonify({"files": files})
    except Exception as e:
        logger.error(f"Error getting user media: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/view_media/<media_type>/<user_id>/<filename>")
def view_media(media_type, user_id, filename):
    if 'admin_logged_in' not in session:
        return "Unauthorized", 401
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if not user: return "User not found", 404
        
        username = user[0]
        media_path = os.path.join(get_user_folder(username), media_type, secure_filename(filename))
        if not os.path.exists(media_path):
            return "File not found", 404
        return send_file(media_path)
    except Exception as e:
        logger.error(f"Error sending media file: {e}")
        return "Error", 500
    finally:
        conn.close()


@app.route("/get_admin_activity", methods=["GET"])
def get_admin_activity():
    try:
        with open('users/admin/admin_activity.log', 'r') as f:
            activities = [line.strip() for line in f.readlines() if line.strip()]
        return jsonify({"activities": activities[-50:]})
    except Exception as e:
        logger.error(f"Error getting admin activity: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/overall_network_usage", methods=["GET"])
def overall_network_usage():
    try:
        return jsonify(psutil.net_io_counters()._asdict())
    except Exception as e:
        logger.error(f"Error getting network usage: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/create_shared_folder/<user_id>", methods=["POST"])
def create_shared_folder(user_id):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            return jsonify({"error": "User not found"}), 404
            
        username = result[0]
        shared_folder = os.path.join(get_user_folder(username), "shared")
        os.makedirs(shared_folder, exist_ok=True)
        
        access_file = os.path.join(shared_folder, "file_access.txt")
        if not os.path.exists(access_file):
            with open(access_file, 'w') as f:
                f.write("read:True\nwrite:True\n")  # Default to enabled for testing
        
        try:
            log_file_access(username, "create_shared_folder", {})
        except Exception as _:
            pass
        return jsonify({"status": "folder_created"})
    except Exception as e:
        logger.error(f"Error creating shared folder: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/update_file_access/<user_id>", methods=["POST"])
def update_file_access(user_id):
    try:
        data = request.json
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            return jsonify({"error": "User not found"}), 404
            
        username = result[0]
        access_file = os.path.join(get_user_folder(username), "shared", "file_access.txt")
        with open(access_file, 'w') as f:
            f.write(f"read:{data.get('read', False)}\n")
            f.write(f"write:{data.get('write', False)}\n")
        try:
            log_file_access(username, "update_file_access", {"read": data.get('read', False), "write": data.get('write', False)})
        except Exception as _:
            pass
        
        return jsonify({"status": "access_updated"})
    except Exception as e:
        logger.error(f"Error updating file access: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

def check_file_access(user_id):
    """Helper function to check file access permissions for a user"""
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            return None, None
        
        username = result[0]
        shared_folder = os.path.join(get_user_folder(username), "shared")
        os.makedirs(shared_folder, exist_ok=True)
        
        access_file = os.path.join(shared_folder, "file_access.txt")
        access = {"read": True, "write": True}  # Default to enabled
        
        if os.path.exists(access_file):
            try:
                with open(access_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("read:"):
                            access["read"] = line.split(":")[1].strip().lower() == "true"
                        elif line.startswith("write:"):
                            access["write"] = line.split(":")[1].strip().lower() == "true"
            except Exception as e:
                logger.error(f"Error reading access file: {e}")
        else:
            # Create default access file
            with open(access_file, 'w') as f:
                f.write("read:True\nwrite:True\n")
        
        conn.close()
        return access, username
    except Exception as e:
        logger.error(f"Error checking file access: {e}")
        if 'conn' in locals():
            conn.close()
        return None, None

@app.route("/get_file_access/<user_id>", methods=["GET"])
def get_file_access(user_id):
    try:
        access, username = check_file_access(user_id)
        if not access or not username:
            return jsonify({"error": "User not found"}), 404
        
        try:
            log_file_access(username, "get_file_access", access)
        except Exception as e:
            logger.error(f"Error logging file access: {e}")
        return jsonify(access)
    except Exception as e:
        logger.error(f"Error getting file access: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/list_shared_files/<user_id>", methods=["GET"])
def list_shared_files(user_id):
    try:
        # Check file access permissions
        access, username = check_file_access(user_id)
        if not access or not username:
            return jsonify({"error": "User not found"}), 404
        
        # Check read permission
        if not access.get("read", False):
            logger.warning(f"User {username} (ID: {user_id}) attempted to list files without read permission")
            return jsonify({"error": "Read access denied"}), 403
        
        shared_folder = os.path.join(get_user_folder(username), "shared")
        files = []
        
        os.makedirs(shared_folder, exist_ok=True)
        
        for f in os.listdir(shared_folder):
            if f != "file_access.txt" and os.path.isfile(os.path.join(shared_folder, f)):
                stat = os.stat(os.path.join(shared_folder, f))
                files.append({
                    "name": f,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
        
        # Log listing action (summary only)
        try:
            log_file_access(username, "list_shared_files", {"count": len(files)})
        except Exception as _:
            pass
        return jsonify({"files": files})
    except Exception as e:
        logger.error(f"Error listing shared files: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/upload_file/<user_id>", methods=["POST"])
def upload_file(user_id):
    try:
        # Check file access permissions
        access, username = check_file_access(user_id)
        if not access or not username:
            return jsonify({"error": "User not found"}), 404
        
        # Check write permission
        if not access.get("write", False):
            logger.warning(f"User {username} (ID: {user_id}) attempted to upload file without write permission")
            return jsonify({"error": "Write access denied"}), 403
            
        shared_folder = os.path.join(get_user_folder(username), "shared")
        os.makedirs(shared_folder, exist_ok=True)
        
        # Handle multiple files
        uploaded_files = []
        if 'file' in request.files:
            files = request.files.getlist('file')
            if not files or all(f.filename == '' for f in files):
                return jsonify({"error": "No files selected"}), 400
                
            for file in files:
                if file and file.filename:
                    filename = secure_filename(file.filename)
                    if filename:  # Ensure filename is not empty after sanitization
                        file_path = os.path.join(shared_folder, filename)
                        file.save(file_path)
                        file_size = os.path.getsize(file_path)
                        uploaded_files.append({"filename": filename, "size": file_size})
                        try:
                            log_file_access(username, "upload", {"filename": filename, "size": file_size})
                        except Exception as e:
                            logger.error(f"Error logging file access: {e}")
        
        if not uploaded_files:
            return jsonify({"error": "No valid files uploaded"}), 400
            
        return jsonify({
            "status": "files_uploaded", 
            "uploaded_files": uploaded_files,
            "count": len(uploaded_files)
        })
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/download_file/<user_id>/<filename>", methods=["GET"])
def download_file(user_id, filename):
    try:
        # Check file access permissions
        access, username = check_file_access(user_id)
        if not access or not username:
            return jsonify({"error": "User not found"}), 404
        
        # Check read permission
        if not access.get("read", False):
            logger.warning(f"User {username} (ID: {user_id}) attempted to download file '{filename}' without read permission")
            return jsonify({"error": "Read access denied"}), 403
            
        shared_folder = os.path.join(get_user_folder(username), "shared")
        file_path = os.path.join(shared_folder, secure_filename(filename))
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
            
        try:
            log_file_access(username, "download", {"filename": filename, "size": os.path.getsize(file_path)})
        except Exception as _:
            pass
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        logger.error(f"Error downloading file: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/delete_file/<user_id>/<filename>", methods=["DELETE"])
def delete_file(user_id, filename):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result:
            return jsonify({"error": "User not found"}), 404
            
        username = result[0]
        shared_folder = os.path.join(get_user_folder(username), "shared")
        file_path = os.path.join(shared_folder, secure_filename(filename))
        
        if not os.path.exists(file_path):
            return jsonify({"error": "File not found"}), 404
            
        os.remove(file_path)
        try:
            log_file_access(username, "delete", {"filename": filename})
        except Exception as _:
            pass
        return jsonify({"status": "file_deleted"})
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

@app.route("/debug_file_manager")
def debug_file_manager():
    """Debug page for file manager issues"""
    return render_template("debug_file_manager.html")

@app.route("/file_manager/<user_id>")
def file_manager(user_id):
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username, pc_name FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        
        if not user:
            return "User not found", 404
            
        return render_template("file_manager.html", user_id=user_id, pc_name=user[1])
    except Exception as e:
        logger.error(f"Error loading file manager: {e}")
        return "Error loading file manager", 500
    finally:
        conn.close()

# SocketIO events
@socketio.on('user_heartbeat')
def handle_user_heartbeat(data):
    user_id = data.get('user_id')
    if user_id:
        if user_id not in online_users:
            socketio.emit('user_online', {'user_id': user_id})
            logger.info(f"User {user_id} is online.")
        online_users[user_id] = time.time()
        client_sids[user_id] = request.sid


@socketio.on('watch_webcam')
def handle_watch_webcam(data):
    user_id = data.get('user_id')
    client_sid = client_sids.get(user_id)
    if client_sid:
        webcam_watchers[request.sid] = user_id
        emit('start_webcam_stream', {'user_id': user_id}, to=client_sid)
        logger.info(f"Admin {request.sid} started watching webcam for user {user_id}")
    else:
        emit('client_not_connected', {'user_id': user_id})

@socketio.on('webcam_frame')
def handle_webcam_frame(data):
    user_id = data.get('user_id')
    for admin_sid, watched_user_id in webcam_watchers.items():
        if watched_user_id == user_id:
            emit('webcam_stream', {'user_id': user_id, 'frame': data['frame']}, to=admin_sid)

@socketio.on('request_screenshot')
def handle_request_screenshot(data):
    user_id = data.get('user_id')
    client_sid = client_sids.get(user_id)
    if client_sid:
        emit('take_screenshot', {'user_id': user_id}, to=client_sid)
        logger.info(f"Admin requested screenshot from user {user_id}")

@socketio.on('screenshot_data')
def handle_screenshot_data(data):
    user_id = data.get('user_id')
    for admin_sid, watched_user_id in webcam_watchers.items():
        if watched_user_id == user_id:
            emit('screenshot_stream', {'user_id': user_id, 'frame': data['frame']}, to=admin_sid)

@socketio.on('save_capture')
def handle_save_capture(data):
    user_id = data.get('user_id')
    media_type = data.get('type', 'photos')
    b64_data = data.get('frame')
    
    conn = None
    try:
        conn = sqlite3.connect("../users.db")
        c = conn.cursor()
        c.execute("SELECT username FROM user_data WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if not user: 
            return
        
        username = user[0]
        media_folder = os.path.join(get_user_folder(username), media_type)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"{timestamp}.jpg"
        filepath = os.path.join(media_folder, filename)
        
        image_data = base64.b64decode(b64_data)
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        logger.info(f"Saved {media_type} for {username} as {filename}")

        for admin_sid, watched_user_id in list(webcam_watchers.items()):
            if watched_user_id == user_id:
                emit('capture_saved', {'user_id': user_id, 'filename': filename, 'type': media_type}, to=admin_sid)

    except Exception as e:
        logger.error(f"Error saving capture: {e}")
    finally:
        if conn:
            conn.close()


@socketio.on('stop_watching_webcam')
def handle_stop_watching_webcam(data):
    admin_sid = request.sid
    if admin_sid in webcam_watchers:
        user_id = webcam_watchers[admin_sid]
        client_sid = client_sids.get(user_id)
        if client_sid:
            emit('stop_webcam_stream', to=client_sid)
        del webcam_watchers[admin_sid]
        logger.info(f"Admin {admin_sid} stopped watching {user_id}")



@socketio.on('disconnect')
def handle_disconnect():
    admin_sid = request.sid
    if admin_sid in webcam_watchers:
        user_id = webcam_watchers[admin_sid]
        client_sid = client_sids.get(user_id)
        if client_sid:
            emit('stop_webcam_stream', to=client_sid)
        del webcam_watchers[admin_sid]
        logger.info(f"Admin {admin_sid} disconnected, stopped watching {user_id}")

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)