import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.app import app

with app.test_client() as client:
    response = client.get('/pass-list')
    print(f"Status code: {response.status_code}")
    print(f"Response data length: {len(response.data)}")
    if response.status_code == 200:
        print("SUCCESS! Route is working!")
    else:
        print("ERROR! Route not found!")
        print(response.data.decode('utf-8')[:500])
