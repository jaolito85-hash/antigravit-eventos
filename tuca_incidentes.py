"""Operações de conversa compartilhadas pelo banco e pelo laboratório."""
from datetime import datetime, timezone


class IncidentConversation:
    def recent_incident(self, sender_hash, minutes=10):
        rows = self.incident_rows(sender_hash, minutes)
        return next((r for r in rows if r.get('urgency') in ('Critico', 'Crítico', 'Urgente')), None)

    def update_incident(self, sender_hash, incident, message, reference=False):
        metadata = dict(incident.get('metadata') or {})
        additions = list(metadata.get('conversation_updates') or [])
        if not any(x['inbox_id'] == str(message['id']) for x in additions):
            additions.append({'inbox_id': str(message['id']), 'text': str(message.get('content') or '')[:1000]})
        metadata['conversation_updates'] = additions[-20:]
        if reference:
            metadata['location_reference'] = str(message.get('content') or '')[:1000]
        changes = {'metadata': metadata, 'updated_at': datetime.now(timezone.utc).isoformat()}
        # A referência fica visível no cartão, além do histórico auditável.
        if reference:
            original = str(incident.get('message') or incident.get('content') or '').split('\nReferência informada:')[0]
            changes['message'] = original[:3900] + '\nReferência informada: ' + metadata['location_reference']
        self.save_incident(sender_hash, incident['id'], changes)
        return incident['id']

    def location_target(self, sender_hash, minutes=60):
        rows = self.incident_rows(sender_hash, minutes)
        # Incidente operacional não perde GPS para FAQ ou elogio posterior.
        return next((r for r in rows if r.get('urgency') in ('Critico','Crítico','Urgente')), rows[0] if rows else None)
