import json
from datetime import datetime

EVENTS_FILE = 'execution/events.json'

mock_data = [
    {
        "id": 1,
        "sender": "5511999990001",
        "name": "User 1",
        "message": "Show lindo",
        "timestamp": datetime.now().strftime("%d/%m/%y %H:%M"),
        "category": "Programação & Atrações",
        "region": "N/A",
        "urgency": "Positivo",
        "sentiment": "Positivo",
        "topic": "Show"
    },
    {
        "id": 2,
        "sender": "5511999990002",
        "name": "User 2",
        "message": "Banheiro sujo",
        "timestamp": datetime.now().strftime("%d/%m/%y %H:%M"),
        "category": "Estrutura & Espaço",
        "region": "Banheiros",
        "urgency": "Urgente",
        "sentiment": "Negativo",
        "topic": "Banheiro Sujo"
    },
     {
        "id": 3,
        "sender": "5511999990003",
        "name": "User 3",
        "message": "Banheiro sujo demais",
        "timestamp": datetime.now().strftime("%d/%m/%y %H:%M"),
        "category": "Estrutura & Espaço",
        "region": "Banheiros",
        "urgency": "Urgente",
        "sentiment": "Negativo",
        "topic": "Banheiro Sujo"
    },
    {
        "id": 4,
        "sender": "5511999990004",
        "name": "User 4",
        "message": "Show maravilhoso",
        "timestamp": datetime.now().strftime("%d/%m/%y %H:%M"),
        "category": "Programação & Atrações",
        "region": "N/A",
        "urgency": "Positivo",
        "sentiment": "Positivo",
        "topic": "Show"
    }
]

with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
    json.dump(mock_data, f, ensure_ascii=False, indent=2)

print("Mock data populated.")
