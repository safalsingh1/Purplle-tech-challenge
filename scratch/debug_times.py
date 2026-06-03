import sqlite3
conn = sqlite3.connect('data/store_intelligence.db')

print('Visitor billing events:')
for r in conn.execute('select visitor_id, event_type, zone_id, timestamp from events where store_id="ST1008" and zone_id in ("BILLING_COUNTER", "BILLING_QUEUE")').fetchall():
    print(r)

print('First 10 ST1008 transaction timestamps:')
for r in conn.execute('select timestamp, transaction_id from pos_transactions where store_id="ST1008" order by timestamp limit 10').fetchall():
    print(r)

conn.close()
