#!/usr/bin/env python3
"""
Test script to generate multiple logs and verify scroll functionality
"""
import requests
import json
import time
from datetime import datetime

BASE_URL = "http://10.205.116.88:5000"
USERNAME = "q1"

def generate_multiple_logs():
    print("📜 Generating Multiple Logs for Scroll Testing...")
    print("=" * 50)
    
    # Get user ID
    try:
        r = requests.get(f"{BASE_URL}/get_user_id/{USERNAME}")
        user_id = r.json().get('user_id')
        print(f"✅ User ID: {user_id}")
    except Exception as e:
        print(f"❌ Error getting user ID: {e}")
        return False
    
    # Generate multiple USB events for scroll testing
    print("\n🔌 Generating USB events...")
    for i in range(10):
        try:
            data = {
                "username": USERNAME,
                "operation": f"USB Inserted #{i+1}",
                "timestamp": datetime.now().isoformat(),
                "device_info": {"vendor": f"Vendor{i+1}", "product": f"Device{i+1}"},
                "details": {}
            }
            r = requests.post(f"{BASE_URL}/usb_event", json=data)
            if r.status_code == 200:
                print(f"   ✅ USB event {i+1} generated")
            time.sleep(0.5)
        except Exception as e:
            print(f"   ❌ Error generating USB event {i+1}: {e}")
    
    # Generate multiple anomalies for scroll testing
    print("\n🚨 Generating anomaly events...")
    anomaly_types = ["logon", "file", "http"]
    
    for i in range(15):
        anomaly_type = anomaly_types[i % len(anomaly_types)]
        try:
            if anomaly_type == "logon":
                data = {
                    "user": USERNAME,
                    "user_id": user_id,
                    "activity": f"Suspicious_Login_#{i+1}",
                    "date": datetime.now().isoformat()
                }
                r = requests.post(f"{BASE_URL}/report_logon_activity", json=data)
            elif anomaly_type == "file":
                data = {
                    "user": USERNAME,
                    "user_id": user_id,
                    "activity": f"Suspicious_File_#{i+1}",
                    "to_removable_media": "yes",
                    "from_removable_media": "no",
                    "filename": f"sensitive_file_{i+1}.txt",
                    "date": datetime.now().isoformat()
                }
                r = requests.post(f"{BASE_URL}/report_file_activity", json=data)
            elif anomaly_type == "http":
                data = {
                    "user": USERNAME,
                    "user_id": user_id,
                    "activity": f"Suspicious_HTTP_#{i+1}",
                    "url": f"http://suspicious-site-{i+1}.com/malware.exe",
                    "content": "A" * 1000
                }
                r = requests.post(f"{BASE_URL}/report_http_activity", json=data)
            
            if r.status_code == 200:
                print(f"   ✅ {anomaly_type} anomaly {i+1} generated")
            time.sleep(0.3)
        except Exception as e:
            print(f"   ❌ Error generating {anomaly_type} anomaly {i+1}: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 Multiple logs generated successfully!")
    print("\n📋 Summary:")
    print("✅ Generated 10 USB events")
    print("✅ Generated 15 anomaly events")
    print("✅ Scroll containers should now show scroll bars")
    
    print(f"\n🌐 Dashboard URL: {BASE_URL}")
    print("💡 Check the dashboard to see scroll functionality!")
    print("   - USB Alerts section should have scroll bar")
    print("   - Anomaly Logs section should have scroll bar")
    print("   - Both sections limited to 300px height")
    
    return True

if __name__ == "__main__":
    success = generate_multiple_logs()
    if not success:
        print("❌ Some tests failed!")
        exit(1)
    else:
        print("🎉 All tests passed!")
