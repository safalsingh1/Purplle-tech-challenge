import json
from collections import defaultdict

with open('data/events.jsonl') as f:
    events = [json.loads(l) for l in f if l.strip()]

s1_events = [e for e in events if e['store_id'] == 'STORE_BLR_002']

double_join_visitors = []
for e in s1_events:
    vid = e.get('visitor_id')
    if vid:
        # Let's count how many times this visitor joined the queue
        v_queue_events = [ev for ev in s1_events if ev.get('visitor_id') == vid and ev.get('zone_id') == 'BILLING_QUEUE']
        enters = [ev for ev in v_queue_events if ev.get('event_type') == 'ZONE_ENTER']
        joins = [ev for ev in v_queue_events if ev.get('event_type') == 'BILLING_QUEUE_JOIN']
        if len(enters) > 0 and len(joins) > 0:
            double_join_visitors.append((vid, len(enters), len(joins)))

print('Visitors with BOTH ZONE_ENTER and BILLING_QUEUE_JOIN in Store 1:', double_join_visitors)
