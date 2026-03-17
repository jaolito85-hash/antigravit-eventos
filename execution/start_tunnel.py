from pyngrok import ngrok
import time
import sys

# Open a HTTP tunnel on port 5001
try:
    public_url = ngrok.connect(5001).public_url
    print(f"\nGenereted Webhook URL: {public_url}/webhook")
    print("Mantenha este script rodando (ou o server) para manter o tunel ativo.\n")
    
    # Keep alive
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("Closing Tunnel")
    sys.exit(0)
except Exception as e:
    print(f"Error: {e}")
