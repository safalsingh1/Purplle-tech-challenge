import sqlite3
from datetime import datetime, timedelta
conn = sqlite3.connect('data/store_intelligence.db')

# 1. Get ST1008 transactions
transactions = conn.execute('select timestamp, transaction_id, basket_value_inr from pos_transactions where store_id="ST1008"').fetchall()
print(f'Total ST1008 transactions: {len(transactions)}')

# 2. Get ST1008 visitors
visitors = conn.execute('select distinct visitor_id from events where store_id="ST1008" and is_staff=0').fetchall()
print(f'Total ST1008 visitors: {len(visitors)}')
visitor_ids = {v[0] for v in visitors}

# 3. Check for time overlap: visitor in BILLING_COUNTER/BILLING_QUEUE in prior 5 min of transaction
converted = set()
for txn_ts_str, txn_id, val in transactions:
    txn_ts = datetime.fromisoformat(txn_ts_str.replace("Z", "+00:00"))
    window_start = txn_ts - timedelta(minutes=5)
    window_start_str = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    txn_ts_str_iso = txn_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    billing_visitors = conn.execute('''
        select distinct visitor_id from events
        where store_id="ST1008"
          and event_type in ("ZONE_ENTER", "ZONE_EXIT", "ZONE_DWELL", "BILLING_QUEUE_JOIN")
          and zone_id in ("BILLING_COUNTER", "BILLING_QUEUE")
          and is_staff = 0
          and timestamp >= ?
          and timestamp <= ?
    ''', (window_start_str, txn_ts_str_iso)).fetchall()
    
    for (vid,) in billing_visitors:
        if vid in visitor_ids:
            converted.add(vid)
            print(f'Txn {txn_id} at {txn_ts_str} matched visitor {vid}')

print(f'Converted visitors: {len(converted)}')
conn.close()
