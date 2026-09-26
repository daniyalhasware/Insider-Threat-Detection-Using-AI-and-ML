#!/usr/bin/env python3
"""
Debug script to test file manager functionality
"""
import requests
import json

BASE_URL = "http://localhost:5000"
USER_ID = "15575ae1-2050-4cf7-b4e9-7e307c53d67d"

def debug_file_manager():
    print("🔍 Debugging File Manager...")
    print("=" * 50)
    
    # 1. Test file access permissions
    print("1️⃣ Testing file access permissions...")
    try:
        r = requests.get(f"{BASE_URL}/get_file_access/{USER_ID}")
        print(f"Status: {r.status_code}")
        print(f"Response: {r.json()}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 2. Test file listing
    print("\n2️⃣ Testing file listing...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{USER_ID}")
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Files count: {len(data.get('files', []))}")
        for file in data.get('files', []):
            print(f"  - {file['name']} ({file['size']} bytes)")
    except Exception as e:
        print(f"Error: {e}")
    
    # 3. Test file manager page
    print("\n3️⃣ Testing file manager page...")
    try:
        r = requests.get(f"{BASE_URL}/file_manager/{USER_ID}")
        print(f"Status: {r.status_code}")
        print(f"Content length: {len(r.text)}")
        
        # Check if user_id is in the response
        if USER_ID in r.text:
            print("✅ User ID found in page")
        else:
            print("❌ User ID NOT found in page")
            
        # Check if JavaScript functions are present
        if "loadFiles" in r.text:
            print("✅ loadFiles function found")
        else:
            print("❌ loadFiles function NOT found")
            
        if "checkPermissions" in r.text:
            print("✅ checkPermissions function found")
        else:
            print("❌ checkPermissions function NOT found")
            
    except Exception as e:
        print(f"Error: {e}")
    
    # 4. Test a simple file upload
    print("\n4️⃣ Testing file upload...")
    try:
        test_content = "Debug test file content"
        files = {'file': ('debug_test.txt', test_content, 'text/plain')}
        r = requests.post(f"{BASE_URL}/upload_file/{USER_ID}", files=files)
        print(f"Status: {r.status_code}")
        print(f"Response: {r.json()}")
    except Exception as e:
        print(f"Error: {e}")
    
    # 5. Test file listing again
    print("\n5️⃣ Testing file listing after upload...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{USER_ID}")
        data = r.json()
        print(f"Files count: {len(data.get('files', []))}")
        for file in data.get('files', []):
            print(f"  - {file['name']} ({file['size']} bytes)")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_file_manager()
