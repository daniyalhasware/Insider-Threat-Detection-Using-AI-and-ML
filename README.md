# 🔐 Insider Threat Detection System  

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)  
![Flask](https://img.shields.io/badge/Framework-Flask-lightgreen)   
![Status](https://img.shields.io/badge/Project-Final%20Year%20Major%20Project-orange)  


> A **cross-platform Insider Threat Detection System** that leverages **Machine Learning (Isolation Forest)** for anomaly detection, monitors **system/user activities**, and provides a **real-time admin dashboard** for threat alerts & user management.  

---

## ✨ Key Highlights

- 📡 **Real-Time Monitoring**: Client agents collect logs (CPU, memory, processes, network traffic, USB events).  
- 🤖 **ML-based Detection**: Anomaly detection using **Isolation Forest** with retrain option.  
- 🖥️ **Admin Dashboard**: Flask + WebSockets for live updates, user management, and visualization.  
- 📂 **Secure File Sharing**: Role-based access (read/write), sync, and GUI client (Tkinter).  
- 🛡️ **Cross-Platform Support**: Works on **Windows, Linux, macOS** with OS-specific USB monitoring.  
- 🔔 **Alert System**: Insider threat alerts, USB activity warnings, and anomaly reports in real-time.

## ⚙️ Tech Stack

| Component       | Technology Used                          |
|-----------------|------------------------------------------|
| **Backend**     | Flask, Flask-SocketIO                    |
| **Client**      | Python, Tkinter, psutil, requests        |
| **Database**    | SQLite (Admin + per-user DBs)            |
| **ML Model**    | Isolation Forest (scikit-learn)          |
| **Monitoring**  | psutil, pyudev (Linux), pywin32 + wmi    |
| **Visualization** | Flask templates (HTML/CSS/JS), WebSockets |


## 📊 Admin Dashboard Features

🔑 Login Authentication (default: admin / p@ssw0rd)

👥 User Management – Add, Accept, Reject, Remove users

📈 System Monitoring – CPU, RAM, network, USB activity

⚠️ Alerts Panel – Insider threat alerts, anomaly logs, USB events

📂 File Sharing Manager – Manage shared folders, set access rights

🧠 Model Control – Retrain anomaly detection model with new logs

---

## 📂 Repository Structure


final_year_project/
│── app.py # Flask server & admin dashboard
│── client.py # Cross-platform monitoring client
│── anomaly_detection_model.pkl # Saved ML model (auto-generated)
│── templates/ # HTML templates for dashboard
│── static/ # CSS/JS assets
│── users/ # User data (created at runtime)
│── admin.db # Admin login DB
│── users.db # User accounts DB
│── requirements.txt # Dependencies
│── README.md
│── LICENSE



## 👨‍💻 Author

Arun Adhikari

🎓 B.Tech Final Year Project – Computer Engineering


## 📂 Project Architecture
```mermaid
flowchart TD
    A[Client Agent] -->|Logs, Activity, USB Events| B[Flask Server]
    B -->|Real-time Updates| C[Admin Dashboard]
    B -->|ML Model| D[Anomaly Detection Engine]
    C -->|Alerts & Reports| E[System Admin]
    B -->|File Upload/Download| F[Shared File Storage]
    F --> G[Client File Sync + GUI]
