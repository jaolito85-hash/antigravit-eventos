import requests
import json
import time

def test_webhook_audio(port=5002, duration=10, message_id="test_audio_123"):
    url = f"http://localhost:{port}/webhook"
    
    # Mock Evolution API payload for an audio message
    payload = {
        "event": "messages.upsert",
        "instance": "test_instance",
        "data": {
            "key": {
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": False,
                "id": message_id
            },
            "pushName": "Tester",
            "message": {
                "audioMessage": {
                    "url": "https://example.com/audio.ogg",
                    "mimetype": "audio/ogg",
                    "seconds": duration,
                    "fileSha256": "base64hash",
                    "fileLength": "1000",
                    "ptt": True
                }
            },
            "messageTimestamp": int(time.time())
        }
    }
    
    print(f"--- Testing Audio ({duration}s) on port {port} ---")
    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test 1: Audio too long (> 35s)
    test_webhook_audio(port=5002, duration=45, message_id="long_audio")
    
    # Test 2: Audio within limit (will try to download/transcribe, expecting failure if not real keys/content)
    # But it verifies the duration check logic
    test_webhook_audio(port=5002, duration=10, message_id="valid_audio")
