import os
import json
import time
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

EVENTS_FILE = 'execution/events.json'
CONFIG_FILE = 'execution/config.json'

def load_json(filepath, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default

class SupabaseClient:
    def __init__(self, url, key):
        self.url = url
        self.key = key
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }

    def select(self, table, query_params={}):
        endpoint = f"{self.url}/rest/v1/{table}"
        response = requests.get(endpoint, headers=self.headers, params=query_params)
        if response.status_code >= 400:
            raise Exception(f"Supabase Select Error: {response.text}")
        return response.json()

    def insert(self, table, data):
        endpoint = f"{self.url}/rest/v1/{table}"
        response = requests.post(endpoint, headers=self.headers, json=data)
        if response.status_code >= 400:
            raise Exception(f"Supabase Insert Error: {response.text}")
        return True

def migrate():
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("❌ Error: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        return

    print(f"🔌 Connecting to Supabase (REST): {SUPABASE_URL}")
    client = SupabaseClient(SUPABASE_URL, SUPABASE_KEY)

    # 1. Migrate Configuration (Categories & Regions)
    print("\n📦 Migrating Configuration...")
    config = load_json(CONFIG_FILE, {"categories": [], "regions": []})
    
    # Categories
    for cat in config.get('categories', []):
        try:
            # Check if exists
            existing = client.select('config', {'type': f"eq.category", 'name': f"eq.{cat['name']}"})
            if not existing:
                data = {"type": "category", "name": cat['name'], "color": cat.get('color', '#8b5cf6')}
                client.insert('config', data)
                print(f"   ✅ Category migrated: {cat['name']}")
            else:
                print(f"   ⚠️ Category skipped (exists): {cat['name']}")
        except Exception as e:
            print(f"   ❌ Error migrating category {cat['name']}: {e}")

    # Regions
    for reg in config.get('regions', []):
        try:
            # Check if exists
            existing = client.select('config', {'type': f"eq.region", 'name': f"eq.{reg['name']}"})
            if not existing:
                data = {"type": "region", "name": reg['name']}
                client.insert('config', data)
                print(f"   ✅ Region migrated: {reg['name']}")
            else:
                print(f"   ⚠️ Region skipped (exists): {reg['name']}")
        except Exception as e:
            print(f"   ❌ Error migrating region {reg['name']}: {e}")


    # 2. Migrate Feedbacks
    print("\n💬 Migrating Feedbacks...")
    feedbacks = load_json(EVENTS_FILE, [])
    # Sort by ID ascending (oldest first)
    feedbacks.sort(key=lambda x: x.get('id', 0))
    
    count = 0
    for fb in feedbacks:
        try:
            # Check if exists (using sender + timestamp as cleaner unique key than message)
            # URL encoding needed for some characters
            # Let's simple check by id if we preserve it, but we are letting ID auto increment.
            # Checking message and sender
            params = {
                'message': f"eq.{fb.get('message')}",
                'sender': f"eq.{fb.get('sender')}"
            }
            existing = client.select('feedbacks', params)
            
            if not existing:
                data = {
                    "sender": fb.get('sender'),
                    "name": fb.get('name'),
                    "message": fb.get('message'),
                    "timestamp": fb.get('timestamp'),
                    "category": fb.get('category'),
                    "region": fb.get('region', 'N/A'),
                    "urgency": fb.get('urgency'),
                    "sentiment": fb.get('sentiment'),
                    "topic": fb.get('topic'),
                    "status": fb.get('status', 'aberto'),
                    "resolved_at": fb.get('resolved_at')
                }
                
                client.insert('feedbacks', data)
                print(f"   ✅ Feedback migrated: {fb.get('id')} - {fb.get('category')}")
                count += 1
                time.sleep(0.1) # Rate limit
            else:
                print(f"   ⚠️ Feedback skipped (exists): {fb.get('id')}")
                
        except Exception as e:
            print(f"   ❌ Error migrating feedback {fb.get('id')}: {e}")

    print(f"\n✨ Migration Complete! {count} new feedbacks imported.")

if __name__ == "__main__":
    print("WARNING: This script will migrate data from local JSON files to the Supabase database defined in .env")
    # input("Press Enter to continue or Ctrl+C to cancel...") # Auto-run for agent
    migrate()
