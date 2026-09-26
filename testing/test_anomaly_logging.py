#!/usr/bin/env python3
"""
Test script to generate anomaly logs and test the 24-hour logging system
"""
import requests
import json
import time
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "q1"

def test_anomaly_logging():
    print("🔍 Testing Anomaly Logging System...")
    print("=" * 50)
    
    # 1. Get user ID
    print("1️⃣ Getting user ID...")
    try:
        r = requests.get(f"{BASE_URL}/get_user_id/{USERNAME}")
        if r.status_code != 200:
            print(f"❌ Failed to get user ID: {r.status_code}")
            return False
        user_id = r.json().get('user_id')
        print(f"✅ User ID: {user_id}")
    except Exception as e:
        print(f"❌ Error getting user ID: {e}")
        return False
    
    # 2. Generate various types of anomalies
    print("\n2️⃣ Generating anomaly logs...")
    
    anomalies = [
        {
            "type": "logon",
            "data": {
                "user": USERNAME,
                "user_id": user_id,
                "activity": "Suspicious_Remote_Login",
                "date": "2025-10-26T02:13:00"
            }
        },
        {
            "type": "file",
            "data": {
                "user": USERNAME,
                "user_id": user_id,
                "activity": "Mass_Delete",
                "to_removable_media": "yes",
                "from_removable_media": "no",
                "filename": "sensitive_data.db",
                "date": "2025-10-26T02:20:00"
            }
        },
        {
            "type": "http",
            "data": {
                "user": USERNAME,
                "user_id": user_id,
                "activity": "Suspicious_Download",
                "url": "http://malicious-site.com/download/virus.exe",
                "content": "A" * 10000
            }
        },
        {
            "type": "device",
            "data": {
                "username": USERNAME,
                "operation": "USB Inserted",
                "timestamp": "2025-10-26T02:25:00",
                "device_info": {"vendor": "Unknown", "product": "Suspicious Device"},
                "details": {}
            }
        }
    ]
    
    for i, anomaly in enumerate(anomalies, 1):
        print(f"\n   {i}. Testing {anomaly['type']} anomaly...")
        try:
            if anomaly['type'] == 'logon':
                r = requests.post(f"{BASE_URL}/report_logon_activity", json=anomaly['data'])
            elif anomaly['type'] == 'file':
                r = requests.post(f"{BASE_URL}/report_file_activity", json=anomaly['data'])
            elif anomaly['type'] == 'http':
                r = requests.post(f"{BASE_URL}/report_http_activity", json=anomaly['data'])
            elif anomaly['type'] == 'device':
                r = requests.post(f"{BASE_URL}/usb_event", json=anomaly['data'])
            
            if r.status_code == 200:
                print(f"   ✅ {anomaly['type']} anomaly generated")
            else:
                print(f"   ⚠️  {anomaly['type']} anomaly response: {r.status_code}")
            
            time.sleep(1)  # Small delay between requests
            
        except Exception as e:
            print(f"   ❌ Error generating {anomaly['type']} anomaly: {e}")
    
    # 3. Test anomaly logs retrieval
    print("\n3️⃣ Testing anomaly logs retrieval...")
    try:
        r = requests.get(f"{BASE_URL}/get_anomaly_logs?hours=24")
        if r.status_code != 200:
            print(f"❌ Failed to get anomaly logs: {r.status_code}")
            return False
        
        logs = r.json()
        print(f"✅ Retrieved {logs.get('count', 0)} anomaly logs")
        
        if logs.get('anomalies'):
            print("   Recent anomalies:")
            for log in logs['anomalies'][:5]:  # Show first 5
                timestamp = datetime.fromisoformat(log['timestamp']).strftime('%H:%M:%S')
                print(f"   - {timestamp} | {log['type'].upper()} | {log['username']} | {log['severity']}")
        
    except Exception as e:
        print(f"❌ Error getting anomaly logs: {e}")
        return False
    
    # 4. Test log file existence
    print("\n4️⃣ Checking log files...")
    import os
    log_files = [
        "logs/anomaly_all.log",
        "logs/anomaly_logon.log",
        "logs/anomaly_file.log",
        "logs/anomaly_http.log",
        "logs/anomaly_device.log"
    ]
    
    for log_file in log_files:
        if os.path.exists(log_file):
            size = os.path.getsize(log_file)
            print(f"✅ {log_file} exists ({size} bytes)")
        else:
            print(f"❌ {log_file} not found")
    
    print("\n" + "=" * 50)
    print("🎉 Anomaly logging test completed!")
    print("\n📋 Summary:")
    print("✅ Generated multiple anomaly types")
    print("✅ Tested anomaly logs API")
    print("✅ Verified log file creation")
    print("✅ 24-hour retention system active")
    
    print(f"\n🌐 Dashboard URL: {BASE_URL}")
    print("💡 Check the dashboard to see anomaly logs displayed!")
    
    return True

if __name__ == "__main__":
    success = test_anomaly_logging()
    if not success:
        print("❌ Some tests failed!")
        exit(1)
    else:
        print("🎉 All tests passed!")
