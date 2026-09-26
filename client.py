import requests
import platform
import uuid
import json
import time
import psutil
import sys
import logging
from datetime import datetime
import os
import threading
import sqlite3
import shutil
import socket
import tkinter as tk
import base64
from tkinter import ttk, messagebox, filedialog
import webbrowser
import cv2
from PIL import Image, ImageTk, ImageGrab, ImageDraw, ImageFont
import socketio
import subprocess
from PIL import Image

try:
    import cv2
    from mss import mss
except ImportError:
    print("Warning: opencv-python or mss not installed. Webcam and screenshot features will be disabled.")
    cv2 = None
    mss = None

if platform.system() == "Windows":
    try:
        import wmi
    except ImportError:
        print("Warning: pywin32/wmi not installed. USB monitoring won't work on Windows.")
        wmi = None
else:
    wmi = None
    try:
        import pyudev
    except ImportError:
        print("Warning: pyudev not installed. USB monitoring won't work on Linux.")
        pyudev = None


# Configuration
SERVER_URL = "http://192.168.0.102:5000"
REPORT_INTERVAL = 30
LOG_UPDATE_INTERVAL = 10
FILE_SYNC_INTERVAL = 60
LOCATION_UPDATE_INTERVAL = 3600
HEARTBEAT_INTERVAL = 10
RECONNECT_DELAY = 5

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('client.log'),
        logging.StreamHandler()
    ]
)

# SocketIO client and reconnection helpers
sio = socketio.Client()
reconnect_lock = threading.Lock()
reconnect_thread = None
shutdown_event = threading.Event()

def connect_with_retry():
    """Connect to the Socket.IO server, retrying until successful or shutdown requested."""
    while not shutdown_event.is_set():
        try:
            sio.connect(SERVER_URL, wait=True)
            logging.info("Socket.IO connection established.")
            return
        except Exception as e:
            logging.error(f"Socket.IO connection failed: {e}")
            time.sleep(RECONNECT_DELAY)

def schedule_reconnect():
    """Start a background thread to reconnect if not already running."""
    global reconnect_thread
    if shutdown_event.is_set() or sio.connected:
        return
    with reconnect_lock:
        if reconnect_thread and reconnect_thread.is_alive():
            return
        reconnect_thread = threading.Thread(target=reconnect_worker, daemon=True)
        reconnect_thread.start()

def reconnect_worker():
    """Try to reconnect until successful or shutdown requested."""
    while not shutdown_event.is_set():
        if sio.connected:
            return
        try:
            logging.info("Attempting to reconnect to Socket.IO server...")
            sio.connect(SERVER_URL, wait=True)
            logging.info("Reconnected to Socket.IO server.")
            return
        except Exception as e:
            logging.error(f"Reconnection attempt failed: {e}")
            time.sleep(RECONNECT_DELAY)

# Ensure directories exist
os.makedirs("logs", exist_ok=True)
os.makedirs("shared", exist_ok=True)


webcam_thread = None
webcam_thread_lock = threading.Lock()
stop_webcam_stream_event = threading.Event()
gui_root = None  # Global reference to GUI root window
gui_instance = None  # Track FileSharingGUI instance for status updates

def update_gui_remote_status(message):
    if gui_instance:
        try:
            gui_instance.update_remote_status(message)
        except Exception:
            logging.exception("Failed to update GUI remote status")

def generate_placeholder_image(text="Screenshot unavailable"):
    width, height = 640, 480
    image = Image.new("RGB", (width, height), (30, 30, 30))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 24)
    except Exception:
        font = ImageFont.load_default()
    text_width, text_height = draw.textsize(text, font=font)
    draw.text(
        ((width - text_width) / 2, (height - text_height) / 2),
        text,
        fill=(255, 255, 255),
        font=font
    )
    return image


class FileSharingGUI:
    def __init__(self, root, user_id, username):
        self.root = root
        self.user_id = user_id
        self.username = username
        self.root.title(f"File Sharing - {username}")
        self.file_access = {"read": False, "write": False}  # Track current permissions
        self.remote_status_var = tk.StringVar(value="Remote access idle")
        self.setup_ui()
        self.check_permissions()
        self.refresh_files()
        global gui_instance
        gui_instance = self
        
    def setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.status_var = tk.StringVar()
        self.status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.update_status("Ready")
        self.tree = ttk.Treeview(main_frame, columns=('name', 'size', 'modified'), show='headings')
        self.tree.heading('name', text='File Name')
        self.tree.heading('size', text='Size')
        self.tree.heading('modified', text='Modified')
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Refresh", command=self.refresh_files).pack(side=tk.LEFT, padx=5)
        self.download_btn = ttk.Button(button_frame, text="Download", command=self.download_file)
        self.download_btn.pack(side=tk.LEFT, padx=5)
        self.upload_btn = ttk.Button(button_frame, text="Upload", command=self.upload_file)
        self.upload_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Open Local Folder", command=self.open_local_folder).pack(side=tk.LEFT, padx=5)
        self.view_online_btn = ttk.Button(button_frame, text="View Online", command=self.view_online)
        self.view_online_btn.pack(side=tk.LEFT, padx=5)
        ttk.Label(main_frame, textvariable=self.remote_status_var, foreground="blue").pack(fill=tk.X, pady=(10, 0))
        
    def update_status(self, message):
        self.status_var.set(message)
    
    def update_remote_status(self, message):
        self.root.after(0, lambda: self.remote_status_var.set(message))
    
    def check_permissions(self):
        """Check and update file access permissions from server"""
        try:
            response = requests.get(f"{SERVER_URL}/get_file_access/{self.user_id}")
            if response.status_code == 200:
                self.file_access = response.json()
                # Update button states based on permissions
                if self.download_btn:
                    self.download_btn.config(state=tk.NORMAL if self.file_access.get("read") else tk.DISABLED)
                if self.upload_btn:
                    self.upload_btn.config(state=tk.NORMAL if self.file_access.get("write") else tk.DISABLED)
                if self.view_online_btn:
                    self.view_online_btn.config(state=tk.NORMAL if self.file_access.get("read") else tk.DISABLED)
                logging.info(f"File access permissions updated: read={self.file_access.get('read')}, write={self.file_access.get('write')}")
            else:
                logging.error(f"Failed to get file access permissions: {response.status_code}")
                # Default to no access on error
                self.file_access = {"read": False, "write": False}
        except Exception as e:
            logging.error(f"Error checking file access permissions: {e}")
            self.file_access = {"read": False, "write": False}
        
        # Schedule next permission check
        self.root.after(5000, self.check_permissions)
    
    def refresh_files(self):
        """Load files from server and display them"""
        try:
            # Check permissions first
            if not self.file_access.get("read", False):
                # Clear existing items
                for item in self.tree.get_children():
                    self.tree.delete(item)
                self.tree.insert('', 'end', values=("No read access", "", ""))
                self.update_status("No read access to files")
                # Schedule next refresh
                self.root.after(5000, self.refresh_files)
                return
            
            self.update_status("Loading files...")
            
            # Clear existing items
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            # Get files from server
            response = requests.get(f"{SERVER_URL}/list_shared_files/{self.user_id}")
            if response.status_code == 200:
                data = response.json()
                files = data.get('files', [])
                
                # Add files to tree
                for file in files:
                    size_str = self.format_file_size(file['size'])
                    modified_str = datetime.fromisoformat(file['modified']).strftime('%Y-%m-%d %H:%M:%S')
                    self.tree.insert('', 'end', values=(file['name'], size_str, modified_str))
                
                self.update_status(f"Loaded {len(files)} files")
            else:
                self.update_status(f"Error loading files: {response.status_code}")
                
        except Exception as e:
            self.update_status(f"Error: {str(e)}")
            logging.error(f"Error refreshing files: {e}")
        
        # Schedule next refresh
        self.root.after(5000, self.refresh_files)
    
    def format_file_size(self, bytes_size):
        """Format file size in human readable format"""
        if bytes_size == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB"]
        i = 0
        while bytes_size >= 1024 and i < len(size_names) - 1:
            bytes_size /= 1024.0
            i += 1
        return f"{bytes_size:.1f} {size_names[i]}"

    def download_file(self):
        """Download selected file"""
        # Check read permission
        if not self.file_access.get("read", False):
            messagebox.showerror("Access Denied", "You do not have read access to files")
            logging.warning(f"User {self.username} attempted to download file without read permission")
            return
        
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a file to download")
            return
        
        item = self.tree.item(selected[0])
        filename = item['values'][0]
        
        # Check if it's the "No read access" message
        if filename == "No read access":
            return
        
        try:
            # Ask user where to save the file
            save_path = filedialog.asksaveasfilename(
                title="Save file as",
                initialfile=filename,
                defaultextension=""
            )
            
            if not save_path:
                return
            
            # Download file from server
            url = f"{SERVER_URL}/download_file/{self.user_id}/{filename}"
            response = requests.get(url)
            
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                messagebox.showinfo("Success", f"File {filename} downloaded successfully")
                self.update_status(f"Downloaded {filename}")
                logging.info(f"Downloaded file {filename} for user {self.username}")
            elif response.status_code == 403:
                messagebox.showerror("Access Denied", "You do not have permission to download this file")
                logging.warning(f"User {self.username} denied download access for {filename}")
            else:
                messagebox.showerror("Error", f"Failed to download file: {response.status_code}")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to download file: {str(e)}")
            logging.error(f"Error downloading file {filename}: {e}")

    def upload_file(self):
        """Upload file to server"""
        # Check write permission
        if not self.file_access.get("write", False):
            messagebox.showerror("Access Denied", "You do not have write access to upload files")
            logging.warning(f"User {self.username} attempted to upload file without write permission")
            return
        
        filepath = filedialog.askopenfilename(title="Select file to upload")
        if not filepath:
            return
        
        filename = os.path.basename(filepath)
        
        try:
            self.update_status(f"Uploading {filename}...")
            
            # Upload file to server
            with open(filepath, 'rb') as f:
                files = {'file': (filename, f, 'application/octet-stream')}
                response = requests.post(f"{SERVER_URL}/upload_file/{self.user_id}", files=files)
            
            if response.status_code == 200:
                data = response.json()
                messagebox.showinfo("Success", f"File {filename} uploaded successfully")
                self.update_status(f"Uploaded {filename}")
                logging.info(f"Uploaded file {filename} for user {self.username}")
                # Refresh file list
                self.refresh_files()
            elif response.status_code == 403:
                messagebox.showerror("Access Denied", "You do not have permission to upload files")
                self.update_status("Upload denied")
                logging.warning(f"User {self.username} denied upload access")
            else:
                messagebox.showerror("Error", f"Failed to upload file: {response.status_code}")
                self.update_status("Upload failed")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload file: {str(e)}")
            self.update_status("Upload failed")
            logging.error(f"Error uploading file {filename}: {e}")

    def open_local_folder(self):
        """Open local shared folder"""
        try:
            local_folder = os.path.join(os.getcwd(), "shared")
            os.makedirs(local_folder, exist_ok=True)
            
            if platform.system() == "Windows":
                os.startfile(local_folder)
            elif platform.system() == "Darwin":  # macOS
                os.system(f"open '{local_folder}'")
            else:  # Linux
                os.system(f"xdg-open '{local_folder}'")
                
            self.update_status("Opened local shared folder")
            logging.info(f"Opened local shared folder for user {self.username}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open local folder: {str(e)}")
            logging.error(f"Error opening local folder: {e}")

    def view_online(self):
        """Open selected file in browser"""
        # Check read permission
        if not self.file_access.get("read", False):
            messagebox.showerror("Access Denied", "You do not have read access to view files")
            logging.warning(f"User {self.username} attempted to view file without read permission")
            return
        
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("No Selection", "Please select a file to view online")
            return
        
        item = self.tree.item(selected[0])
        filename = item['values'][0]
        
        # Check if it's the "No read access" message
        if filename == "No read access":
            return
        
        try:
            # Open file in browser using download endpoint
            url = f"{SERVER_URL}/download_file/{self.user_id}/{filename}"
            webbrowser.open(url)
            self.update_status(f"Opening {filename} in browser")
            logging.info(f"Opened file {filename} in browser for user {self.username}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open file: {str(e)}")
            logging.error(f"Error opening file {filename}: {e}")

def log_logon_activity(user_id, username, activity):
    try:
        requests.post(
            f"{SERVER_URL}/report_logon_activity",
            json={
                "user_id": user_id,
                "user": username,
                "activity": activity,
                "date": datetime.now().isoformat()
            }
        )
    except Exception as e:
        logging.error(f"Error sending logon activity: {e}")

def log_file_activity(user_id, username, filename, activity):
    try:
        requests.post(
            f"{SERVER_URL}/report_file_activity",
            json={
                "id": str(uuid.uuid4()),
                "date": datetime.now().isoformat(),
                "user": username,
                "user_id": user_id,
                "pc": platform.node(),
                "filename": filename,
                "activity": activity,
                "to_removable_media": "True",
                "from_removable_media": "False"
            }
        )
    except Exception as e:
        logging.error(f"Error sending file activity: {e}")

def log_http_activity(user_id, username):
    try:
        requests.post(
            f"{SERVER_URL}/report_http_activity",
            json={
                "id": str(uuid.uuid4()),
                "date": datetime.now().isoformat(),
                "user": username,
                "user_id": user_id,
                "url": "http://suspicious-site.com/data-exfil",
                "activity": "WWW Visit",
                "content": "This is simulated content of a visited webpage."
            }
        )
    except Exception as e:
        logging.error(f"Error sending http activity: {e}")

def validate_password(username, password):
    try:
        resp = requests.post(
            f"{SERVER_URL}/validate_user_password",
            json={"username": username, "password": password}
        )
        return resp.status_code == 200 and resp.json().get("status") == "valid"
    except Exception as e:
        logging.error(f"Server connection error: {e}")
        return False

def register_user(username, password):
    user_id = str(uuid.uuid4())
    pc_name = platform.node()
    platform_name = platform.system()

    try:
        resp = requests.post(
            f"{SERVER_URL}/add_user",
            json={
                "user_id": user_id,
                "username": username,
                "password": password,
                "pc_name": pc_name,
                "platform": platform_name
            }
        )
        if resp.status_code == 200 and resp.json().get("status") == "user_added":
            logging.info("User added successfully. Waiting for admin acceptance...")
            return user_id
        logging.error("Failed to add user.")
        return None
    except Exception as e:
        logging.error(f"Error sending initial data: {e}")
        return None

def check_acceptance(user_id):
    while True:
        try:
            response = requests.get(f"{SERVER_URL}/user_details/{user_id}")
            if response.status_code == 200:
                user_data = response.json()
                if "error" in user_data:
                    logging.error(user_data["error"])
                    sys.exit(1)
                
                accepted_status = user_data.get("accepted")
                if accepted_status == 1:
                    logging.info("User accepted by admin. Starting monitoring...")
                    return True
                elif accepted_status == -1:
                    logging.error("Request rejected by admin. Exiting...")
                    sys.exit(1)
                logging.info("Waiting for admin acceptance...")
            else:
                logging.error(f"Error fetching user details. Status: {response.status_code}")
        except Exception as e:
            logging.error(f"Error checking acceptance status: {e}")
        time.sleep(5)

def get_system_info():
    return {
        "hostname": socket.gethostname(),
        "os": platform.system(),
        "os_version": platform.version(),
        "processor": platform.processor(),
        "ram": f"{round(psutil.virtual_memory().total / (1024**3), 2)} GB",
        "last_boot": datetime.fromtimestamp(psutil.boot_time()).strftime('%Y-%m-%d %H:%M:%S')
    }

def get_network_connections():
    connections = []
    try:
        net_io = psutil.net_io_counters(pernic=True)

        for conn in psutil.net_connections(kind='inet'):
            if conn.status == 'ESTABLISHED' and conn.raddr:
                interface = None
                for nic, addrs in psutil.net_if_addrs().items():
                    if any(addr.address == conn.laddr.ip for addr in addrs):
                        interface = nic
                        break
                
                sent_bytes = net_io[interface].bytes_sent if interface and interface in net_io else 0
                recv_bytes = net_io[interface].bytes_recv if interface and interface in net_io else 0

                connections.append({
                    "protocol": "TCP",
                    "remote_ip": conn.raddr.ip,
                    "port": conn.raddr.port,
                    "status": conn.status,
                    "pid": conn.pid,
                    "interface": interface,
                    "sent_bytes": sent_bytes,
                    "received_bytes": recv_bytes
                })
    except Exception as e:
        logging.error(f"Error getting network connections: {e}")
    return connections

def get_browser_history():
    history = []
    browsers = {
        "chrome": {
            "windows": os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data', 'Default', 'History'),
            "linux": os.path.expanduser("~/.config/google-chrome/Default/History"),
            "darwin": os.path.expanduser("~/Library/Application Support/Google/Chrome/Default/History")
        },
        "firefox": {
            "windows": os.path.join(os.getenv('APPDATA', ''), 'Mozilla', 'Firefox', 'Profiles'),
            "linux": os.path.expanduser("~/.mozilla/firefox"),
            "darwin": os.path.expanduser("~/Library/Application Support/Firefox/Profiles")
        }
    }

    def fetch_chrome_history(db_path):
        if db_path and os.path.exists(db_path):
            try:
                temp_db = db_path + "_temp"
                shutil.copy2(db_path, temp_db)
                conn = sqlite3.connect(temp_db)
                cursor = conn.cursor()
                cursor.execute("SELECT url, title, last_visit_time FROM urls ORDER BY last_visit_time DESC LIMIT 50")
                for row in cursor.fetchall():
                    history.append({
                        'url': row[0],
                        'title': row[1],
                        'time': datetime.fromtimestamp(row[2]/1000000-11644473600).strftime('%Y-%m-%d %H:%M:%S')
                    })
                conn.close()
                if os.path.exists(temp_db):
                    os.remove(temp_db)
            except Exception as e:
                logging.error(f"Error fetching Chrome history: {e}")

    def fetch_firefox_history(profile_path):
        if profile_path and os.path.exists(profile_path):
            try:
                profiles = [d for d in os.listdir(profile_path) if os.path.isdir(os.path.join(profile_path, d)) and d.endswith('.default')]
                if not profiles:
                    return
                latest_profile = profiles[0]
                db_path = os.path.join(profile_path, latest_profile, 'places.sqlite')
                
                if os.path.exists(db_path):
                    temp_db = db_path + "_temp"
                    shutil.copy2(db_path, temp_db)
                    conn = sqlite3.connect(temp_db)
                    cursor = conn.cursor()
                    cursor.execute("SELECT url, title, last_visit_date FROM moz_places JOIN moz_historyvisits ON moz_places.id = moz_historyvisits.place_id ORDER BY last_visit_date DESC LIMIT 50")
                    for row in cursor.fetchall():
                        history.append({
                            'url': row[0],
                            'title': row[1],
                            'time': datetime.fromtimestamp(row[2]/1000000).strftime('%Y-%m-%d %H:%M:%S')
                        })
                    conn.close()
                    if os.path.exists(temp_db):
                        os.remove(temp_db)
            except Exception as e:
                logging.error(f"Error fetching Firefox history: {e}")

    system = platform.system().lower()
    if system == 'windows':
        fetch_chrome_history(browsers["chrome"]["windows"])
        fetch_firefox_history(browsers["firefox"]["windows"])
    elif system == 'linux':
        fetch_chrome_history(browsers["chrome"]["linux"])
        fetch_firefox_history(browsers["firefox"]["linux"])
    elif system == 'darwin':
        fetch_chrome_history(browsers["chrome"]["darwin"])
        fetch_firefox_history(browsers["firefox"]["darwin"])
    
    return history

def get_downloads():
    downloads = []
    seen_paths = set()  # Track seen file paths to avoid duplicates
    
    try:
        if platform.system() == 'Windows':
            downloads_path = os.path.join(os.getenv('USERPROFILE', ''), 'Downloads')
            try:
                edge_history = os.path.join(os.getenv('LOCALAPPDATA', ''), 'Microsoft', 'Edge', 'User Data', 'Default', 'History')
                chrome_history = os.path.join(os.getenv('LOCALAPPDATA', ''), 'Google', 'Chrome', 'User Data', 'Default', 'History')
                
                for history_db in [edge_history, chrome_history]:
                    if os.path.exists(history_db):
                        temp_db = history_db + "_temp"
                        shutil.copy2(history_db, temp_db)
                        conn = sqlite3.connect(temp_db)
                        cursor = conn.cursor()
                        cursor.execute("SELECT target_path, total_bytes, start_time FROM downloads ORDER BY start_time DESC LIMIT 20")
                        for row in cursor.fetchall():
                            if os.path.exists(row[0]):
                                file_path = row[0]
                                # Skip if we've already seen this file path
                                if file_path not in seen_paths:
                                    seen_paths.add(file_path)
                                    filename = os.path.basename(file_path)
                                    downloads.append({
                                        'filename': filename,
                                        'path': file_path,
                                        'size': f"{round(row[1] / (1024*1024), 2)} MB" if row[1] else "N/A",
                                        'timestamp': datetime.fromtimestamp(row[2]/1000000-11644473600).strftime('%Y-%m-%d %H:%M:%S')
                                    })
                        conn.close()
                        if os.path.exists(temp_db):
                            os.remove(temp_db)
            except Exception as e:
                logging.error(f"Error reading browser download history: {e}")
        else:
            downloads_path = os.path.expanduser('~/Downloads')
        
        # Add files from Downloads folder, avoiding duplicates
        if os.path.exists(downloads_path):
            for f in os.listdir(downloads_path):
                full_path = os.path.join(downloads_path, f)
                if os.path.isfile(full_path) and full_path not in seen_paths:
                    seen_paths.add(full_path)
                    stat = os.stat(full_path)
                    downloads.append({
                        'filename': f,
                        'path': full_path,
                        'size': f"{round(stat.st_size / (1024*1024), 2)} MB",
                        'timestamp': datetime.fromtimestamp(stat.st_ctime).strftime('%Y-%m-%d %H:%M:%S')
                    })
    except Exception as e:
        logging.error(f"Error getting downloads: {e}")
    
    return sorted(downloads, key=lambda x: x['timestamp'], reverse=True)[:20]

def collect_web_activity(username):
    return {
        "visited_sites": get_browser_history(),
        "downloaded_files": get_downloads(),
        "username": username
    }

def report_web_activity(user_id, username):
    while True:
        try:
            activity = collect_web_activity(username)
            if not activity.get("visited_sites") and not activity.get("downloaded_files"):
                logging.info("No web activity to report")
                time.sleep(REPORT_INTERVAL)
                continue
            resp = requests.post(f"{SERVER_URL}/report_web_activity/{user_id}", json=activity)
            if resp.status_code == 200:
                logging.info("Web activity reported successfully")
            else:
                logging.error(f"Failed to report web activity: {resp.text}")
        except Exception as e:
            logging.error(f"Error reporting web activity: {e}")
        time.sleep(REPORT_INTERVAL)

# Global variable to store previous packet stats for delta calculation
_previous_packet_stats = {}

def get_network_packets():
    """Analyze network packets using psutil - returns interface-level delta values only"""
    global _previous_packet_stats
    packet_analysis = []
    current_time = time.time()
    
    try:
        # Get interface statistics with delta calculation
        net_io = psutil.net_io_counters(pernic=True)
        
        for interface, stats in net_io.items():
            # Skip loopback interface (lo) - it's always active for localhost communication
            if interface == 'lo':
                continue
            # Only include interfaces with actual traffic
            if stats.bytes_sent > 0 or stats.bytes_recv > 0:
                # Calculate deltas from previous measurement
                prev_key = f"interface_{interface}"
                prev_stats = _previous_packet_stats.get(prev_key, {})
                
                bytes_sent_delta = stats.bytes_sent - prev_stats.get('bytes_sent', stats.bytes_sent)
                bytes_recv_delta = stats.bytes_recv - prev_stats.get('bytes_recv', stats.bytes_recv)
                packets_sent_delta = stats.packets_sent - prev_stats.get('packets_sent', stats.packets_sent)
                packets_recv_delta = stats.packets_recv - prev_stats.get('packets_recv', stats.packets_recv)
                errors_in_delta = stats.errin - prev_stats.get('errors_in', stats.errin)
                errors_out_delta = stats.errout - prev_stats.get('errors_out', stats.errout)
                drops_in_delta = stats.dropin - prev_stats.get('drops_in', stats.dropin)
                drops_out_delta = stats.dropout - prev_stats.get('drops_out', stats.dropout)
                
                # Calculate time delta (default to 30 seconds if first measurement)
                time_delta = current_time - prev_stats.get('timestamp', current_time - 30)
                if time_delta <= 0:
                    time_delta = 30
                
                # Calculate rates (per second)
                bytes_sent_rate = bytes_sent_delta / time_delta if time_delta > 0 else 0
                bytes_recv_rate = bytes_recv_delta / time_delta if time_delta > 0 else 0
                packets_sent_rate = packets_sent_delta / time_delta if time_delta > 0 else 0
                packets_recv_rate = packets_recv_delta / time_delta if time_delta > 0 else 0
                
                # Store current stats for next calculation
                _previous_packet_stats[prev_key] = {
                    'bytes_sent': stats.bytes_sent,
                    'bytes_recv': stats.bytes_recv,
                    'packets_sent': stats.packets_sent,
                    'packets_recv': stats.packets_recv,
                    'errors_in': stats.errin,
                    'errors_out': stats.errout,
                    'drops_in': stats.dropin,
                    'drops_out': stats.dropout,
                    'timestamp': current_time
                }
                
                packet_analysis.append({
                    'interface': interface,
                    'bytes_sent': bytes_sent_delta,  # Delta, not cumulative
                    'bytes_recv': bytes_recv_delta,  # Delta, not cumulative
                    'bytes_sent_rate': bytes_sent_rate,  # Bytes per second
                    'bytes_recv_rate': bytes_recv_rate,  # Bytes per second
                    'packets_sent': packets_sent_delta,  # Delta
                    'packets_recv': packets_recv_delta,  # Delta
                    'packets_sent_rate': packets_sent_rate,  # Packets per second
                    'packets_recv_rate': packets_recv_rate,  # Packets per second
                    'errors_in': errors_in_delta,  # Delta
                    'errors_out': errors_out_delta,  # Delta
                    'drops_in': drops_in_delta,  # Delta
                    'drops_out': drops_out_delta,  # Delta
                    'total_bytes_sent': stats.bytes_sent,  # Cumulative for reference
                    'total_bytes_recv': stats.bytes_recv,  # Cumulative for reference
                    'timestamp': datetime.now().isoformat()
                })
            
    except Exception as e:
        logging.error(f"Error analyzing network packets: {e}")
    
    return packet_analysis

def report_email_activity(user_id, username):
    """Report email activity to server"""
    while True:
        try:
            emails = get_email_activity()
            if emails:
                resp = requests.post(
                    f"{SERVER_URL}/report_email_activity/{user_id}",
                    json={"username": username, "emails": emails}
                )
                if resp.status_code == 200:
                    logging.info(f"Email activity reported: {len(emails)} entries")
                else:
                    logging.error(f"Failed to report email activity: {resp.text}")
        except Exception as e:
            logging.error(f"Error reporting email activity: {e}")
        time.sleep(REPORT_INTERVAL * 2)  # Report every 60 seconds

def report_packet_analysis(user_id, username):
    """Report network packet analysis to server"""
    while True:
        try:
            packets = get_network_packets()
            if packets:
                resp = requests.post(
                    f"{SERVER_URL}/report_packet_analysis/{user_id}",
                    json={"username": username, "packets": packets}
                )
                if resp.status_code == 200:
                    logging.info(f"Packet analysis reported: {len(packets)} entries")
                else:
                    logging.error(f"Failed to report packet analysis: {resp.text}")
        except Exception as e:
            logging.error(f"Error reporting packet analysis: {e}")
        time.sleep(REPORT_INTERVAL)  # Report every 30 seconds

def report_network_activity(user_id, username):
    while True:
        try:
            activity = {"network_activity": get_network_connections(), "username": username}
            resp = requests.post(f"{SERVER_URL}/report_network_activity/{user_id}", json=activity)
            if resp.status_code == 200:
                logging.info("Network activity reported successfully")
            else:
                logging.error(f"Failed to report network activity: {resp.text}")
        except Exception as e:
            logging.error(f"Error reporting network activity: {e}")
        time.sleep(REPORT_INTERVAL)

def get_geolocation():
    try:
        ip = requests.get('https://api.ipify.org').text
        response = requests.get(f'http://ip-api.com/json/{ip}')
        if response.status_code == 200:
            data = response.json()
            if data['status'] == 'success':
                return {
                    'ip': ip,
                    'city': data.get('city', 'Unknown'),
                    'region': data.get('regionName', 'Unknown'),
                    'country': data.get('country', 'Unknown'),
                    'lat': data.get('lat', 0),
                    'lon': data.get('lon', 0),
                    'time': datetime.now().isoformat()
                }
    except Exception as e:
        logging.error(f"Error getting geolocation: {e}")
    return None

def report_location(user_id, username):
    while True:
        try:
            location = get_geolocation()
            if location:
                response = requests.post(f"{SERVER_URL}/report_location/{user_id}", json={"username": username, "location": location})
                if response.status_code == 200:
                    logging.info("Location reported successfully")
        except Exception as e:
            logging.error(f"Error reporting location: {e}")
        time.sleep(LOCATION_UPDATE_INTERVAL)

def log_usb_event(event_type, operation, device_info, username, details={}):
    timestamp = datetime.now().isoformat()
    log_file = os.path.join("logs", "usb.txt")
    with open(log_file, "a") as f:
        f.write(f"{timestamp} - {operation}: {device_info} | Details: {details}\n")
    try:
        requests.post(
            f"{SERVER_URL}/usb_event",
            json={
                "username": username,
                "event_type": event_type,
                "operation": operation,
                "device_info": device_info,
                "timestamp": timestamp,
                "pc_name": platform.node(),
                "details": details
            }
        )
    except Exception as e:
        logging.error(f"Error sending USB event: {e}")

def get_linux_usb_snapshot():
    devices = set()
    sys_usb_path = "/sys/bus/usb/devices"
    if os.path.exists(sys_usb_path):
        for entry in os.listdir(sys_usb_path):
            if not entry.startswith("usb"):  # Skip root hubs
                try:
                    device_dir = os.path.join(sys_usb_path, entry)
                    # Check if it's a real device
                    if not os.path.exists(os.path.join(device_dir, "manufacturer")):
                        continue

                    vendor_file = os.path.join(device_dir, "manufacturer")
                    product_file = os.path.join(device_dir, "product")
                    
                    vendor = open(vendor_file).read().strip() if os.path.exists(vendor_file) else "Unknown"
                    product = open(product_file).read().strip() if os.path.exists(product_file) else "Unknown"
                    
                    # Create a more stable identifier
                    devices.add(f"{entry}:{vendor}-{product}")
                except Exception:
                    continue
    return devices

def poll_usb_devices_linux(username):
    logging.info("USB polling fallback started for Linux")
    previous_devices = get_linux_usb_snapshot()
    recent_events = {}  # Track recent events: {operation_device: timestamp}
    EVENT_COOLDOWN = 3  # Reduced to 3 seconds - only prevent rapid duplicate events
    
    while True:
        try:
            current_devices = get_linux_usb_snapshot()
            inserted = current_devices - previous_devices
            removed = previous_devices - current_devices
            
            current_time = time.time()
            
            # Clean up old events from tracking (keep only last 3 seconds)
            recent_events = {k: v for k, v in recent_events.items() if current_time - v < EVENT_COOLDOWN}
            
            for device_info in inserted:
                # Use operation+device as key to allow same device to be inserted/removed multiple times
                event_key = f"insert_{device_info}"
                if event_key not in recent_events:
                    logging.info(f"[POLL] USB Inserted: {device_info}")
                    log_usb_event("Inserted", "USB Inserted", device_info, username)
                    recent_events[event_key] = current_time
                    
            for device_info in removed:
                # Use operation+device as key
                event_key = f"remove_{device_info}"
                if event_key not in recent_events:
                    logging.info(f"[POLL] USB Removed: {device_info}")
                    log_usb_event("Removed", "USB Removed", device_info, username)
                    recent_events[event_key] = current_time
                    
            previous_devices = current_devices
        except Exception as e:
            logging.error(f"USB polling error: {e}")
        time.sleep(2)  # Reduced polling interval to 2 seconds for faster detection

def monitor_usb_windows(username):
    if not wmi: return
    c = wmi.WMI()
    insert_watcher = c.Win32_USBControllerDevice.watch_for("creation")
    remove_watcher = c.Win32_USBControllerDevice.watch_for("deletion")
    logging.info("USB monitoring started for Windows")
    
    recent_events = {}  # Track recent events: {operation_device: timestamp}
    EVENT_COOLDOWN = 3  # Reduced to 3 seconds - only prevent rapid duplicate events
    
    while True:
        try:
            current_time = time.time()
            # Clean up old events from tracking (keep only last 3 seconds)
            recent_events = {k: v for k, v in recent_events.items() if current_time - v < EVENT_COOLDOWN}
            
            insert_event = insert_watcher(timeout_ms=5000)
            if insert_event:
                device_info = str(insert_event.Dependent)
                # Use operation+device as key to allow same device to be inserted/removed multiple times
                event_key = f"insert_{device_info}"
                if event_key not in recent_events:
                    logging.info(f"USB Inserted: {device_info}")
                    log_usb_event("Inserted", "USB Inserted", device_info, username)
                    recent_events[event_key] = current_time

                    # --- NEW: Simulate a file copy event after insertion ---
                    time.sleep(2)  # A small delay to simulate the action
                    file_details = {
                        "filename": "confidential_report.docx", 
                        "size": "2.5 MB",
                        "from_location": "C:\\Users\\User\\Documents",
                        "to_location": f"E:\\", 
                        "direction": "to_usb"
                    }
                    log_usb_event("File Copied", "File Copied", device_info, username, details=file_details)
                
            remove_event = remove_watcher(timeout_ms=2000)
            if remove_event:
                device_info = str(remove_event.Dependent)
                # Use operation+device as key
                event_key = f"remove_{device_info}"
                if event_key not in recent_events:
                    logging.info(f"USB Removed: {device_info}")
                    log_usb_event("Removed", "USB Removed", device_info, username)
                    recent_events[event_key] = current_time
        except Exception as e:
            if 'timed out' not in str(e).lower():
                logging.error(f"USB monitoring error: {e}")

def monitor_usb_linux(username):
    if not pyudev:
        logging.warning("pyudev not available; falling back to polling strategy for USB monitoring.")
        poll_usb_devices_linux(username)
        return
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem='usb')
    logging.info("USB monitoring started for Linux")
    
    recent_events = {}  # Track recent events: {operation_device: timestamp}
    EVENT_COOLDOWN = 3  # Reduced to 3 seconds - only prevent rapid duplicate events
    
    try:
        for device in iter(monitor.poll, None):
            try:
                current_time = time.time()
                device_path = str(device.device_path)
                
                # Clean up old events from tracking (keep only last 3 seconds)
                recent_events = {k: v for k, v in recent_events.items() if current_time - v < EVENT_COOLDOWN}
                devtype = device.get('DEVTYPE')
                if devtype != 'usb_device':
                    continue
                if device.action == "add":
                    # Use operation+device as key to allow same device to be inserted/removed multiple times
                    event_key = f"insert_{device_path}"
                    if event_key not in recent_events:
                        logging.info(f"USB Inserted: {device_path}")
                        log_usb_event("Inserted", "USB Inserted", device_path, username)
                        recent_events[event_key] = current_time
                elif device.action == "remove":
                    # Use operation+device as key
                    event_key = f"remove_{device_path}"
                    if event_key not in recent_events:
                        logging.info(f"USB Removed: {device_path}")
                        log_usb_event("Removed", "USB Removed", device_path, username)
                        recent_events[event_key] = current_time
            except Exception as event_error:
                logging.error(f"Error processing USB event: {event_error}")
    except Exception as e:
        logging.error(f"pyudev monitor failed: {e}. Switching to polling fallback.")
        poll_usb_devices_linux(username)

def sync_shared_files(user_id, username):
    while True:
        try:
            # Default to no access to avoid accidental uploads/downloads on failure
            access = {"read": False, "write": False}

            access_resp = requests.get(f"{SERVER_URL}/get_file_access/{user_id}")
            if access_resp.status_code == 200:
                # Ensure the payload is a dict with expected keys
                payload = access_resp.json() or {}
                access["read"] = bool(payload.get("read", False))
                access["write"] = bool(payload.get("write", False))
            else:
                logging.error(f"Failed to get file access: {access_resp.status_code}")

            if not access.get("read"):
                # Skip syncing if read access is disabled
                time.sleep(FILE_SYNC_INTERVAL)
                continue

            list_resp = requests.get(f"{SERVER_URL}/list_shared_files/{user_id}")
            if list_resp.status_code == 200:
                server_files = {f['name']: f for f in list_resp.json().get("files", [])}
                for filename, file_info in server_files.items():
                    local_path = os.path.join("shared", filename)
                    server_mtime = datetime.fromisoformat(file_info['modified']).timestamp()
                    if not os.path.exists(local_path) or os.path.getmtime(local_path) < server_mtime:
                        logging.info(f"Downloading file: {filename}")
                        download_resp = requests.get(f"{SERVER_URL}/download_file/{user_id}/{filename}", stream=True)
                        if download_resp.status_code == 200:
                            with open(local_path, 'wb') as f:
                                shutil.copyfileobj(download_resp.raw, f)
                            os.utime(local_path, (server_mtime, server_mtime))
                        else:
                            logging.error(f"Failed to download file {filename}: {download_resp.status_code}")
            else:
                logging.error(f"Failed to list shared files: {list_resp.status_code}")
                server_files = {}
            if access.get("write"):
                local_files = {}
                for f in os.listdir("shared"):
                    if f != "file_access.txt":
                        full_path = os.path.join("shared", f)
                        if os.path.isfile(full_path):
                            stat = os.stat(full_path)
                            local_files[f] = {"size": stat.st_size, "modified": stat.st_mtime}
                for filename, file_info in local_files.items():
                    if filename not in server_files or file_info['modified'] > datetime.fromisoformat(server_files[filename]['modified']).timestamp():
                        logging.info(f"Uploading file: {filename}")
                        with open(os.path.join("shared", filename), 'rb') as f:
                            files = {'file': (filename, f)}
                            upload_resp = requests.post(f"{SERVER_URL}/upload_file/{user_id}", files=files)
                            if upload_resp.status_code != 200:
                                logging.error(f"Failed to upload file {filename}: {upload_resp.text}")
        except Exception as e:
            logging.error(f"Error syncing files: {e}")
        time.sleep(FILE_SYNC_INTERVAL)

def send_system_logs(user_id, username):
    login_time = datetime.now().isoformat()
    while True:
        try:
            response = requests.get(f"{SERVER_URL}/user_details/{user_id}")
            if response.status_code != 200 or response.json().get("accepted") != 1:
                logging.error("User no longer accepted. Exiting...")
                sys.exit(1)
            
            # Get USB count and risk score from server response
            usb_count = response.json().get("usb_count", 0)
            risk_score = response.json().get("risk_score", 0)

            logs = []
            
            # First pass: collect all process PIDs and initialize CPU percent calculation
            # This is needed because cpu_percent() requires two calls to calculate properly
            process_pids = []
            for proc in psutil.process_iter(['pid']):
                try:
                    pid = proc.info['pid']
                    process_pids.append(pid)
                    # Initialize CPU percent calculation (first call)
                    proc.cpu_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            # Small delay to allow CPU percent calculation
            time.sleep(0.1)
            
            # Second pass: collect all process information with proper CPU percent
            for pid in process_pids:
                try:
                    proc = psutil.Process(pid)
                    
                    # Get process name
                    try:
                        process_name = proc.name()
                        if not process_name or process_name == '':
                            # Try to get executable name
                            try:
                                exe_path = proc.exe()
                                if exe_path:
                                    process_name = os.path.basename(exe_path)
                                else:
                                    process_name = f"Process_{pid}"
                            except (psutil.AccessDenied, psutil.NoSuchProcess):
                                process_name = f"Process_{pid}"
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        process_name = f"Process_{pid}"
                    
                    # Calculate CPU percent (second call after initialization)
                    try:
                        cpu_percent = proc.cpu_percent()
                        if cpu_percent is None:
                            cpu_percent = 0.0
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        cpu_percent = 0.0
                    
                    # Get memory percent
                    try:
                        memory_percent = proc.memory_percent()
                        if memory_percent is None:
                            memory_percent = 0.0
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        memory_percent = 0.0
                    
                    # Get create time
                    try:
                        create_time = proc.create_time()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        create_time = 0
                    
                    # Build process info dictionary
                    log_entry = {
                        'pid': pid,
                        'name': process_name,
                        'cpu_percent': round(cpu_percent, 2),
                        'memory_percent': round(memory_percent, 2),
                        'create_time': create_time
                    }
                    
                    # Add exe path if available
                    try:
                        exe_path = proc.exe()
                        if exe_path:
                            log_entry['exe'] = exe_path
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass
                    
                    logs.append(log_entry)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            logging.info(f"Collected {len(logs)} processes for user {username}")
            network_io = psutil.net_io_counters()
            network_traffic_data = network_io._asdict() if network_io else {}
            data = {
                "logs": json.dumps(logs),
                "network_traffic": json.dumps(network_traffic_data),
                "login_time": login_time,
                "logout_time": datetime.now().isoformat(),
                "system_info": json.dumps(get_system_info()),
                "usb_count": usb_count,
                "risk_score": risk_score
            }
            resp = requests.post(f"{SERVER_URL}/update_activity/{user_id}", json=data)
            if resp.status_code == 200:
                logging.info(f"Successfully sent {len(logs)} process logs to server for user {username}")
            else:
                logging.error(f"Failed to update logs: Status {resp.status_code}, Response: {resp.text}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Network error sending system logs: {e}")
        except Exception as e:
            logging.error(f"Error in system log collection: {e}", exc_info=True)
        time.sleep(LOG_UPDATE_INTERVAL)

def send_heartbeat(user_id):
    while True:
        try:
            if sio.connected:
                sio.emit('user_heartbeat', {'user_id': user_id})
        except Exception as e:
            logging.error(f"Error sending heartbeat: {e}")
        time.sleep(HEARTBEAT_INTERVAL)

def webcam_stream_worker(user_id):
    global webcam_thread
    if not cv2:
        logging.warning("Webcam functionality unavailable (cv2 not installed).")
        return
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        logging.error("Could not open webcam.")
        return
    logging.info(f"Webcam stream started for user {user_id}")
    try:
        while not stop_webcam_stream_event.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.5)
                continue
            frame = cv2.resize(frame, (640, 480))
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            b64_frame = base64.b64encode(buffer).decode('utf-8')
            try:
                sio.emit('webcam_frame', {'user_id': user_id, 'frame': b64_frame})
            except Exception as e:
                logging.error(f"Failed to send webcam frame: {e}")
                break
            sio.sleep(0.1)
    finally:
        cap.release()
        stop_webcam_stream_event.clear()
        with webcam_thread_lock:
            webcam_thread = None
        logging.info(f"Webcam stream stopped for user {user_id}")
        update_gui_remote_status("Remote access idle")

def take_screenshot_worker(user_id):
    from io import BytesIO
    try:
        img = None
        if mss:
            try:
                with mss() as sct:
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception as e:
                logging.error(f"mss screenshot failed: {e}")
        if img is None:
            logging.warning("Using ImageGrab fallback for screenshot capture.")
            try:
                img = ImageGrab.grab()
            except Exception as grab_error:
                logging.error(f"ImageGrab failed: {grab_error}")
                img = generate_placeholder_image("Screenshot unavailable")

        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        b64_frame = base64.b64encode(buffered.getvalue()).decode('utf-8')
        sio.emit('screenshot_data', {'user_id': user_id, 'frame': b64_frame})
        logging.info(f"Screenshot sent for user {user_id}")
        update_gui_remote_status("Screenshot sent to admin console")
    except Exception as e:
        logging.error(f"Failed to take or send screenshot: {e}")
        update_gui_remote_status("Screenshot failed")

@sio.event
def connect():
    logging.info("Connected to server.")

@sio.event
def disconnect():
    logging.info("Disconnected from server.")
    schedule_reconnect()

@sio.on('user_logged_out')
def on_user_logged_out(data):
    user_id = data.get('user_id')
    logging.info(f"Received remote logout command for user {user_id}. Shutting down.")
    shutdown_event.set()
    
    # Try to close GUI window if it exists
    try:
        global gui_root, gui_instance
        if gui_root is not None:
            logging.info("Closing GUI window...")
            gui_root.quit()
            gui_root.destroy()
            gui_root = None
            gui_instance = None
    except Exception as e:
        logging.error(f"Error closing GUI: {e}")
    
    # Disconnect from SocketIO
    try:
        if sio.connected:
            logging.info("Disconnecting from SocketIO...")
            sio.disconnect()
    except Exception as e:
        logging.error(f"Error disconnecting SocketIO: {e}")
    
    # Force exit - this will terminate the entire process including all threads
    logging.info("Client shutting down due to logout command.")
    os._exit(0)

@sio.on('start_webcam_stream')
def on_start_webcam_stream(data):
    global webcam_thread
    user_id = data.get('user_id')
    with webcam_thread_lock:
        if webcam_thread is None or not webcam_thread.is_alive():
            stop_webcam_stream_event.clear()
            webcam_thread = threading.Thread(target=webcam_stream_worker, args=(user_id,), daemon=True)
            webcam_thread.start()
            logging.info("Webcam streaming thread started.")
            update_gui_remote_status("Remote webcam stream active")
        else:
            logging.info("Webcam stream already running; start request ignored.")

@sio.on('stop_webcam_stream')
def on_stop_webcam_stream(data=None):
    global webcam_thread
    stop_webcam_stream_event.set()
    with webcam_thread_lock:
        thread = webcam_thread
    if thread and thread.is_alive():
        thread.join(timeout=2)
    with webcam_thread_lock:
        webcam_thread = None
    logging.info("Webcam streaming thread stopped via server command.")
    update_gui_remote_status("Remote access idle")

@sio.on('take_screenshot')
def on_take_screenshot(data):
    user_id = data.get('user_id')
    update_gui_remote_status("Capturing screenshot for remote request...")
    threading.Thread(target=take_screenshot_worker, args=(user_id,), daemon=True).start()

def main():
    print("Monitoring Client\n" + "="*20)
    print("1. New User\n2. Existing User")
    choice = input("Select option (1/2): ").strip()

    if choice == "1":
        admin_pass = input("Admin password: ").strip()
        if admin_pass != "p@ssw0rd":
            logging.error("Invalid admin password")
            return
        username = input("Username: ").strip()
        password = input("Password: ").strip()
        user_id = register_user(username, password)
        if not user_id:
            return
    elif choice == "2":
        username = input("Username: ").strip()
        password = input("Password: ").strip()
        if not validate_password(username, password):
            logging.error("Invalid password")
            return
        try:
            response = requests.get(f"{SERVER_URL}/get_user_id/{username}")
            if response.status_code == 200:
                user_id = response.json().get("user_id")
            else:
                logging.error("User not found")
                return
        except Exception as e:
            logging.error(f"Error fetching user ID: {e}")
            return
    else:
        logging.error("Invalid choice")
        return

    if not check_acceptance(user_id):
        return

    connect_with_retry()

    log_logon_activity(user_id, username, "Logon")

    threads = []
    
    heartbeat_thread = threading.Thread(target=send_heartbeat, args=(user_id,))
    heartbeat_thread.daemon = True
    threads.append(heartbeat_thread)
    heartbeat_thread.start()

    if platform.system() == "Windows":
        usb_thread = threading.Thread(target=monitor_usb_windows, args=(username,))
    elif platform.system() == "Linux":
        usb_thread = threading.Thread(target=monitor_usb_linux, args=(username,))
    else:
        usb_thread = None
    
    if usb_thread:
        usb_thread.daemon = True
        threads.append(usb_thread)
        usb_thread.start()

    syslog_thread = threading.Thread(target=send_system_logs, args=(user_id, username))
    syslog_thread.daemon = True
    threads.append(syslog_thread)
    syslog_thread.start()

    web_thread = threading.Thread(target=report_web_activity, args=(user_id, username))
    web_thread.daemon = True
    threads.append(web_thread)
    web_thread.start()

    network_thread = threading.Thread(target=report_network_activity, args=(user_id, username))
    network_thread.daemon = True
    threads.append(network_thread)
    network_thread.start()

    packet_thread = threading.Thread(target=report_packet_analysis, args=(user_id, username))
    packet_thread.daemon = True
    threads.append(packet_thread)
    packet_thread.start()

    file_thread = threading.Thread(target=sync_shared_files, args=(user_id, username))
    file_thread.daemon = True
    threads.append(file_thread)
    file_thread.start()

    location_thread = threading.Thread(target=report_location, args=(user_id, username))
    location_thread.daemon = True
    threads.append(location_thread)
    location_thread.start()

    global gui_root
    global gui_root, gui_instance
    gui_root = tk.Tk()
    FileSharingGUI(gui_root, user_id, username)
    gui_root.mainloop()

    shutdown_event.set()
    gui_instance = None
    sio.disconnect()

if __name__ == "__main__":
    main()