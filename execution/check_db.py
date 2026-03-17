import os
import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json"
}

def check():
    print(f"Checking {URL}...")
    try:
        # Check Config
        res = requests.get(f"{URL}/rest/v1/config?select=*", headers=headers)
        if res.status_code != 200:
            print(f"Error: {res.text}")
            return
        
        data = res.json()
        print(f"Found {len(data)} items in 'config' table.")
        cats = [d['name'] for d in data if d['type'] == 'category']
        regs = [d['name'] for d in data if d['type'] == 'region']
        
        print(f"Categories ({len(cats)}): {cats}")
        print(f"Regions ({len(regs)}): {regs}")

    except Exception as e:
        print(f"Exception: {e}")

if __name__ == "__main__":
    check()
