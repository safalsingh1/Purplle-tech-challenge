import json
with open('data/events.jsonl') as f:
    events = [json.loads(l) for l in f if l.strip()]

s1_events = [e for e in events if e['store_id'] == 'STORE_BLR_002']
staff_vids = set(e['visitor_id'] for e in s1_events if e['visitor_id'] is not None and e.get('is_staff') == True)

for e in s1_events:
    if e.get('event_type') == 'ENTRY' and e.get('visitor_id') in staff_vids:
        print(f'Staff {e.get("visitor_id")} ENTRY event: is_staff={e.get("is_staff")}')
