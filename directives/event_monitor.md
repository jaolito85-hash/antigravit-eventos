# Directive: Handle Event Reports

## Goal
Receive WhatsApp messages from event attendees, acknowledge them immediately, and log them for the dashboard.

## Triggers
- Incoming Webhook from Evolution API (type: `messages.upsert`)

## Steps
1. **Validation**: Ensure message is not from the bot itself ( `key.fromMe` should be false).
2. **Extraction**:
   - `remoteJid`: The user's phone number.
   - `pushName`: User's name.
   - `text`: The content of the report (e.g., "Banheiro sujo").
3. **Action**:
   - **Log**: Save report to the Event Dashboard queue.
   - **Reply**: Send WhatsApp message to `remoteJid`:
     > "Recebemos sua mensagem! A equipe do evento já foi notificada e está verificando."

## Edge Cases
- **Media messages**: If user sends photo/audio, reply with: "Por favor, envie apenas texto descrevendo o problema." (Optional for MVP)
