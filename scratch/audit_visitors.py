import json

with open('data/events.jsonl') as f:
    events = [json.loads(l) for l in f if l.strip()]

print("=== GROUND TRUTH: What did the cameras actually see? ===")
print()

for s_id, label in [('STORE_BLR_002', 'Store 1 (Bengaluru Central)'), ('ST1008', 'Store 2 (Brigade Road)')]:
    s_events = [e for e in events if e['store_id'] == s_id]
    staff_ids = set(e['visitor_id'] for e in s_events if e['visitor_id'] and e.get('is_staff') == True)

    # ENTRY events from entry cameras only
    entry_vids = set(
        e['visitor_id'] for e in s_events
        if e['visitor_id'] and e.get('event_type') == 'ENTRY' and e['visitor_id'] not in staff_ids
    )
    exit_vids = set(
        e['visitor_id'] for e in s_events
        if e['visitor_id'] and e.get('event_type') == 'EXIT' and e['visitor_id'] not in staff_ids
    )
    reentry_vids = set(
        e['visitor_id'] for e in s_events
        if e['visitor_id'] and e.get('event_type') == 'REENTRY' and e['visitor_id'] not in staff_ids
    )

    print(f"{label}:")
    print(f"  Customers who entered (ENTRY event): {len(entry_vids)}")
    print(f"  Customers who exited  (EXIT event):  {len(exit_vids)}")
    print(f"  Customers who re-entered (REENTRY):  {len(reentry_vids)}")
    print(f"  Staff members identified: {len(staff_ids)}")
    print(f"  CORRECT unique_visitors metric: {len(entry_vids)}")
    print()
