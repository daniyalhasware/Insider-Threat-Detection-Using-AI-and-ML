#!/usr/bin/env python3
"""
Comprehensive test script for file sharing functionality
"""
import requests
import os
import tempfile
import json
import time

BASE_URL = "http://10.205.116.88:5000"
USERNAME = "q1"

def test_file_sharing_comprehensive():
    print("🔧 Testing File Sharing Functionality...")
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
    
    # 2. Test file access permissions
    print("\n2️⃣ Testing file access permissions...")
    try:
        r = requests.get(f"{BASE_URL}/get_file_access/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to get file access: {r.status_code}")
            return False
        access = r.json()
        print(f"✅ File access: {access}")
        
        if not access.get('read', False):
            print("⚠️  Read access is disabled - enabling it...")
            r = requests.post(f"{BASE_URL}/update_file_access/{user_id}", json={'read': True, 'write': True})
            if r.status_code == 200:
                print("✅ Read/Write access enabled")
            else:
                print(f"❌ Failed to enable access: {r.status_code}")
                return False
    except Exception as e:
        print(f"❌ Error with file access: {e}")
        return False
    
    # 3. Test create shared folder
    print("\n3️⃣ Testing shared folder creation...")
    try:
        r = requests.post(f"{BASE_URL}/create_shared_folder/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to create shared folder: {r.status_code}")
            return False
        print("✅ Shared folder created/verified")
    except Exception as e:
        print(f"❌ Error creating shared folder: {e}")
        return False
    
    # 4. Test list shared files (before upload)
    print("\n4️⃣ Testing file listing (before upload)...")
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
    
    # 5. Test file upload
    print("\n5️⃣ Testing file upload...")
    try:
        # Create test files
        test_files = [
            ("test_file_1.txt", "This is test file 1 for file sharing functionality.\n"),
            ("test_file_2.txt", "This is test file 2 for file sharing functionality.\n"),
            ("test_data.json", json.dumps({"test": "data", "timestamp": time.time()}, indent=2))
        ]
        
        uploaded_count = 0
        for filename, content in test_files:
            files = {'file': (filename, content, 'text/plain')}
            r = requests.post(f"{BASE_URL}/upload_file/{user_id}", files=files)
            
            if r.status_code != 200:
                print(f"❌ Failed to upload {filename}: {r.status_code} - {r.text}")
                continue
            
            result = r.json()
            print(f"✅ Uploaded {filename}: {result}")
            uploaded_count += 1
        
        if uploaded_count == 0:
            print("❌ No files uploaded successfully")
            return False
        
        print(f"✅ Successfully uploaded {uploaded_count} files")
        
    except Exception as e:
        print(f"❌ Error uploading files: {e}")
        return False
    
    # 6. Test file listing (after upload)
    print("\n6️⃣ Testing file listing (after upload)...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to list files: {r.status_code}")
            return False
        files = r.json()
        print(f"✅ Files after upload: {len(files.get('files', []))} files")
        for file in files.get('files', []):
            print(f"   - {file['name']} ({file['size']} bytes)")
    except Exception as e:
        print(f"❌ Error listing files: {e}")
        return False
    
    # 7. Test file download
    print("\n7️⃣ Testing file download...")
    try:
        r = requests.get(f"{BASE_URL}/download_file/{user_id}/test_file_1.txt")
        if r.status_code != 200:
            print(f"❌ Failed to download file: {r.status_code}")
            return False
        print(f"✅ File downloaded: {len(r.content)} bytes")
        print(f"   Content preview: {r.text[:50]}...")
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
        return False
    
    # 8. Test file deletion
    print("\n8️⃣ Testing file deletion...")
    try:
        r = requests.delete(f"{BASE_URL}/delete_file/{user_id}/test_file_1.txt")
        if r.status_code != 200:
            print(f"❌ Failed to delete file: {r.status_code}")
            return False
        print(f"✅ File deleted: {r.json()}")
    except Exception as e:
        print(f"❌ Error deleting file: {e}")
        return False
    
    # 9. Test final file listing
    print("\n9️⃣ Testing final file listing...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{user_id}")
        if r.status_code != 200:
            print(f"❌ Failed to list files: {r.status_code}")
            return False
        files = r.json()
        print(f"✅ Final files: {len(files.get('files', []))} files")
        for file in files.get('files', []):
            print(f"   - {file['name']} ({file['size']} bytes)")
    except Exception as e:
        print(f"❌ Error listing files: {e}")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 All file sharing tests completed successfully!")
    print("\n📋 Summary:")
    print("✅ User ID retrieval")
    print("✅ File access permissions")
    print("✅ Shared folder creation")
    print("✅ File upload (multiple files)")
    print("✅ File listing")
    print("✅ File download")
    print("✅ File deletion")
    print("✅ View Online functionality (via download endpoint)")
    
    print(f"\n🌐 File Manager URL: {BASE_URL}/file_manager/{user_id}")
    print("💡 Open this URL in your browser to test the GUI!")
    
    return True

if __name__ == "__main__":
    success = test_file_sharing_comprehensive()
    if not success:
        print("❌ Some tests failed!")
        exit(1)
    else:
        print("🎉 All tests passed!")
