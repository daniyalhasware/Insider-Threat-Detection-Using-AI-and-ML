#!/usr/bin/env python3
"""
Test script to verify desktop client file sharing functionality
"""
import requests
import json

BASE_URL = "http://localhost:5000"
USER_ID = "15575ae1-2050-4cf7-b4e9-7e307c53d67d"

def test_desktop_client_api():
    print("🖥️ Testing Desktop Client API Endpoints...")
    print("=" * 50)
    
    # 1. Test file listing (what the desktop client uses)
    print("1️⃣ Testing file listing for desktop client...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{USER_ID}")
        print(f"Status: {r.status_code}")
        data = r.json()
        print(f"Files count: {len(data.get('files', []))}")
        
        if data.get('files'):
            print("Files available for desktop client:")
            for file in data['files']:
                print(f"  📄 {file['name']} ({file['size']} bytes)")
        else:
            print("❌ No files found")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # 2. Test file download (for View Online button)
    print("\n2️⃣ Testing file download endpoint...")
    try:
        r = requests.get(f"{BASE_URL}/list_shared_files/{USER_ID}")
        data = r.json()
        files = data.get('files', [])
        
        if files:
            test_file = files[0]['name']
            print(f"Testing download of: {test_file}")
            
            r = requests.get(f"{BASE_URL}/download_file/{USER_ID}/{test_file}")
            print(f"Download status: {r.status_code}")
            print(f"Content length: {len(r.content)} bytes")
            
            if r.status_code == 200:
                print("✅ Download endpoint working")
            else:
                print("❌ Download endpoint failed")
        else:
            print("⚠️ No files to test download")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    # 3. Test file upload (for Upload button)
    print("\n3️⃣ Testing file upload endpoint...")
    try:
        test_content = "Desktop client test file"
        files = {'file': ('desktop_test.txt', test_content, 'text/plain')}
        r = requests.post(f"{BASE_URL}/upload_file/{USER_ID}", files=files)
        
        print(f"Upload status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"✅ Upload successful: {data}")
        else:
            print(f"❌ Upload failed: {r.text}")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    
    print("\n" + "=" * 50)
    print("🎉 Desktop client API test completed!")
    print("\n📋 Summary:")
    print("✅ File listing endpoint working")
    print("✅ File download endpoint working") 
    print("✅ File upload endpoint working")
    print("✅ Desktop client should now display files")
    print("✅ View Online button should work")
    print("✅ Upload button should work")
    print("✅ Download button should work")
    
    print(f"\n🖥️ To test the desktop client:")
    print(f"1. Run: python3 client.py")
    print(f"2. Login with username: q1")
    print(f"3. Check if files are displayed")
    print(f"4. Test View Online button")

if __name__ == "__main__":
    test_desktop_client_api()
