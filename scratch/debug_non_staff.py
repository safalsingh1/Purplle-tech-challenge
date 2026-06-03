import sqlite3
conn = sqlite3.connect('data/store_intelligence.db')

print('Non-staff ST1008 billing visits:')
for r in conn.execute('select visitor_id, event_type, zone_id, timestamp, is_staff from events where store_id="ST1008" and zone_id in ("BILLING_COUNTER", "BILLING_QUEUE") and is_staff=0').fetchall():
    print(r)

conn.close()
