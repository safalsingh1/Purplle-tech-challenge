# PROMPT: Generate unit tests for the updated ingest_pos_transactions function that supports both the original schema and the new aggregated order CSV schema (with columns order_id, store_id, order_date, order_time, total_amount). Make sure to cover aggregation of multiple items under the same order, timestamp formatting to ISO-8601 UTC, and avoiding duplicate ingestion.
# CHANGES MADE: Integrated with pytest conftest test_session fixture, added assertions for specific order values, and verified db state.

import os
import tempfile
import pytest
from app.ingestion import ingest_pos_transactions
from app.models import POSTransaction

def test_ingest_original_schema(test_session):
    """Test ingestion of original schema csv format."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
        tmp.write("store_id,transaction_id,timestamp,basket_value_inr\n")
        tmp.write("STORE_BLR_002,TXN_99001,2026-03-03T14:10:00Z,950.50\n")
        tmp_name = tmp.name

    try:
        count = ingest_pos_transactions(tmp_name, test_session)
        assert count == 1

        txn = test_session.query(POSTransaction).filter(POSTransaction.transaction_id == "TXN_99001").first()
        assert txn is not None
        assert txn.store_id == "STORE_BLR_002"
        assert txn.basket_value_inr == 950.50
        assert txn.timestamp == "2026-03-03T14:10:00Z"
    finally:
        os.unlink(tmp_name)


def test_ingest_new_aggregated_schema(test_session):
    """Test ingestion of the new order-based schema with multiple rows per order."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".csv") as tmp:
        tmp.write("order_id,store_id,order_date,order_time,total_amount\n")
        # Order 1 (2 items)
        tmp.write("100000001,ST1008,10-04-2026,16:55:00,150.00\n")
        tmp.write("100000001,ST1008,10-04-2026,16:55:00,350.50\n")
        # Order 2 (1 item)
        tmp.write("100000002,ST1008,10-04-2026,17:30:15,600.00\n")
        tmp_name = tmp.name

    try:
        count = ingest_pos_transactions(tmp_name, test_session)
        assert count == 2

        # Check Order 1 aggregated sum: 150.00 + 350.50 = 500.50
        txn1 = test_session.query(POSTransaction).filter(POSTransaction.transaction_id == "100000001").first()
        assert txn1 is not None
        assert txn1.store_id == "ST1008"
        assert txn1.basket_value_inr == 500.50
        assert txn1.timestamp == "2026-04-10T16:55:00Z"

        # Check Order 2
        txn2 = test_session.query(POSTransaction).filter(POSTransaction.transaction_id == "100000002").first()
        assert txn2 is not None
        assert txn2.store_id == "ST1008"
        assert txn2.basket_value_inr == 600.00
        assert txn2.timestamp == "2026-04-10T17:30:15Z"

        # Verify duplicates are skipped
        count_dup = ingest_pos_transactions(tmp_name, test_session)
        assert count_dup == 0
    finally:
        os.unlink(tmp_name)
