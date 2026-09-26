import requests
import sys
import json


BASE_URL = "http://192.168.1.17:5000"
USERNAME = "a1"
PASSWORD = "1234"


def get_user_id(username: str) -> str:
    url = f"{BASE_URL}/get_user_id/{username}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if "user_id" not in data:
        raise RuntimeError(f"User ID not found for {username}: {data}")
    return data["user_id"]


def post_json(path: str, payload: dict) -> dict:
    url = f"{BASE_URL}{path}"
    r = requests.post(url, json=payload, timeout=15)
    try:
        return r.json()
    except Exception:
        return {"status_code": r.status_code, "text": r.text}


def main():
    try:
        print(f"Fetching user_id for {USERNAME}...")
        user_id = get_user_id(USERNAME)
        print(f"user_id: {user_id}\n")

        # Optional: validate password (not strictly required for alerts)
        print("Validating user password (optional)...")
        val = post_json("/validate_user_password", {"username": USERNAME, "password": PASSWORD})
        print("validate_user_password:", val)

        # # 1) Logon anomaly
        # print("\nTriggering logon anomaly...")
        # logon_payload = {
        #     "user": USERNAME,
        #     "user_id": user_id,
        #     "activity": "Unusual_Remote_Login",
        #     "date": "2025-10-26T02:13:00",  # Sunday ~2 AM
        # }
        # print("/report_logon_activity:", post_json("/report_logon_activity", logon_payload))






        # 2) File anomaly
        print("\nTriggering file anomaly...")
        # file_payload = {
        #     "user": USERNAME,
        #     "user_id": user_id,
        #     "activity": "Mass_Delete",
        #     "to_removable_media": "yes",
        #     "from_removable_media": "no",
        #     "filename": "sensitive.db",
        #     "date": "2025-10-26T02:20:00",
        # }
        # print("/report_file_activity:", post_json("/report_file_activity", file_payload))







        # 3) HTTP anomaly

        # print("\nTriggering HTTP anomaly...")
        # long_body = "A" * 10000
        # http_payload = {
        #     "user": USERNAME,
        #     "user_id": user_id,
        #     "activity": "Suspicious_Download",
        #     "url": "http://example.com/download/very/long/path/with/many/segments/and/query?x=1234567890&y=abcdefghijklmnopqrstuvwxyz",
        #     "content": long_body,
        # }
        # print("/report_http_activity:", post_json("/report_http_activity", http_payload))






        # 4a) USB inserted (device anomaly)

        # print("\nTriggering USB insert (device anomaly)...")
        # usb_insert_payload = {
        #     "username": USERNAME,
        #     "operation": "USB Inserted",
        #     "timestamp": "2025-10-26T02:25:00",
        #     "device_info": {"vendor": "Generic", "product": "USB Flash Drive"},
        #     "details": {},
        # }
        # print("/usb_event (insert):", post_json("/usb_event", usb_insert_payload))





        # 4b) USB file copy (increases risk, emits anomaly)

        # print("\nTriggering USB file copy alert...")
        # usb_copy_payload = {
        #     "username": USERNAME,
        #     "operation": "File Copied",
        #     "timestamp": "2025-10-26T02:26:00",
        #     "device_info": {"vendor": "Generic", "product": "USB Flash Drive"},
        #     "details": {
        #         "filename": "client_data.xlsx",
        #         "direction": "outbound",
        #         "from_location": "C:/Users/q1/Documents/client_data.xlsx",
        #         "to_location": "E:/client_data.xlsx",
        #     },
        # }
        # print("/usb_event (file copied):", post_json("/usb_event", usb_copy_payload))

        # print("\nDone. Keep the admin dashboard open to see alerts and risk score updates.")





    except Exception as e:
        print("Error:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()


