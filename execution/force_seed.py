import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.getenv("SUPABASE_URL")
KEY = os.getenv("SUPABASE_KEY")
CONFIG_FILE = 'execution/config.json'

headers = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal"
}

def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

def seed():
    print(f"🌱 Seeding Config to {URL}")
    
    # 1. Clean existing Config (Dangerous but necessary here)
    # We delete where id > 0 (assuming id is int pkey)
    print("   🧹 Clearing existing config...")
    res = requests.delete(f"{URL}/rest/v1/config?id=gt.0", headers=headers)
    
    # 2. Insert Groups
    config = load_json(CONFIG_FILE)
    
    new_categories = []
    for cat in config.get('categories', []):
        new_categories.append({
            "type": "category", 
            "name": cat['name'], 
            "color": cat.get('color', '#8b5cf6')
        })
    
    new_regions = []
    for reg in config.get('regions', []):
        new_regions.append({
            "type": "region", 
            "name": reg['name']
        })
    
    # Batch Insert
    all_data = new_categories + new_regions
    if not all_data:
        print("   ⚠️ No data to insert!")
        return

    print(f"   📥 Inserting {len(all_data)} items...")
    res = requests.post(f"{URL}/rest/v1/config", headers=headers, json=all_data)
    
    if res.status_code < 300:
        print("   ✅ Success!")
    else:
        print(f"   ❌ Error: {res.text}")

if __name__ == "__main__":
    seed()
