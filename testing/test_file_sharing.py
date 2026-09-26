#!/usr/bin/env python3
"""
Test script for file sharing functionality
"""
import requests
import os
import tempfile
import json

BASE_URL = "http://10.205.116.88:5000"
USERNAME = "q1"

def test_file_sharing():
    print("Testing file sharing functionality...")
    
    # 1. Get user ID
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
    
    # 2. Test file access permissions
    try:
        r = requests.get(f"{BASE_URL}/get_file_access/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to get file access: {r.status_code}")
            return False
        access = r.json()
        print(f"✅ File access: {access}")
    except Exception as e:
        print(f"❌ Error getting file access: {e}")
        return False
    
    # 3. Test list shared files
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to list files: {r.status_code}")
            return False
        files = r.json()
        print(f"✅ Current files: {len(files.get('files', []))} files")
        for file in files.get('files', []):
            print(f"   - {file['name']} ({file['size']} bytes)")
    except Exception as e:
        print(f"❌ Error listing files: {e}")
        return False
    
    # 4. Test file upload
    if access.get('write', False):
        try:
            # Create a test file
            test_content = "This is a test file for file sharing functionality.\n"
            test_filename = "test_file_sharing.txt"
            
            files = {'file': (test_filename, test_content, 'text/plain')}
            r = requests.post(f"{BASE_URL}/upload_file/{user_id}", files=files)
            
            if r.status_code != 200:
                print(f"❌ Failed to upload file: {r.status_code} - {r.text}")
                return False
            
            result = r.json()
            print(f"✅ File uploaded: {result}")
            
            # Verify file appears in list
            r = requests.get(f"{BASE_URL}/list_shared_files/{user_id}")
            files = r.json()
            uploaded_file = next((f for f in files.get('files', []) if f['name'] == test_filename), None)
            if uploaded_file:
                print(f"✅ File verified in list: {uploaded_file['name']} ({uploaded_file['size']} bytes)")
            else:
                print(f"❌ Uploaded file not found in list")
                return False
                
        except Exception as e:
            print(f"❌ Error uploading file: {e}")
            return False
    else:
        print("⚠️  Write access disabled, skipping upload test")
    
    # 5. Test file download
    if access.get('read', False):
        try:
            r = requests.get(f"{BASE_URL}/download_file/{user_id}/test_file_sharing.txt")
            if r.status_code != 200:
                print(f"❌ Failed to download file: {r.status_code}")
                return False
            print(f"✅ File downloaded: {len(r.content)} bytes")
        except Exception as e:
            print(f"❌ Error downloading file: {e}")
            return False
    else:
        print("⚠️  Read access disabled, skipping download test")
    
    # 6. Test file deletion
    if access.get('write', False):
        try:
            r = requests.delete(f"{BASE_URL}/delete_file/{user_id}/test_file_sharing.txt")
            if r.status_code != 200:
                print(f"❌ Failed to delete file: {r.status_code}")
                return False
            print(f"✅ File deleted: {r.json()}")
        except Exception as e:
            print(f"❌ Error deleting file: {e}")
            return False
    else:
        print("⚠️  Write access disabled, skipping delete test")
    
    print("✅ All file sharing tests completed successfully!")
    return True

if __name__ == "__main__":
    success = test_file_sharing()
    if not success:
        print("❌ Some tests failed!")
        exit(1)
    else:
        print("🎉 All tests passed!")
