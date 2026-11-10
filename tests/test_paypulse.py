"""
Unit Test Suite for PayPulse Agentic Treasury & Autonomous Procurement OS.
Compatible with both `python3 -m unittest discover -s tests -v` and `pytest`.
"""

from __future__ import annotations

import unittest

from src.apimatic_paypal_sdk import (
    APIMaticPayPalClient,
    APIMaticSchemaValidationError,
    Money,
    OAuth2TokenManager,
    OrderItem,
    OrderRequest,
    PurchaseUnitRequest,
)
from src.paypulse_engine import PayPulseAgenticTreasury


class TestPayPulseAgenticTreasury(unittest.TestCase):
    def test_01_apimatic_schema_validation_enforces_strict_types(self) -> None:
        with self.assertRaisesRegex(APIMaticSchemaValidationError, "Unsupported currency_code"):
            Money(currency_code="BTC", value="100.00").validate()

        with self.assertRaisesRegex(APIMaticSchemaValidationError, "allows at most 2 decimal places"):
            Money(currency_code="USD", value="19.999").validate()

        item = OrderItem(
            name="H100 AI Node",
            sku="NV-H100",
            quantity=2,
            unit_amount=Money(currency_code="USD", value="2500.00"),
        )
        bad_pu = PurchaseUnitRequest(
            reference_id="REF-1",
            description="Mismatch test",
            amount=Money(currency_code="USD", value="4000.00"),
            custom_id="CUST-1",
            invoice_id="INV-1",
            items=[item],
        )
        with self.assertRaisesRegex(APIMaticSchemaValidationError, "does not match sum of items"):
            bad_pu.validate()

    def test_02_apimatic_oauth2_token_lifecycle_and_refresh(self) -> None:
        fake_time = [1000.0]
        mgr = OAuth2TokenManager("cid_123", "sec_456", clock=lambda: fake_time[0])
        t1 = mgr.get_bearer_token()
        self.assertTrue(t1.startswith("A21AA_"))
        self.assertEqual(mgr.refresh_count, 1)

        fake_time[0] += 3600.0
        t2 = mgr.get_bearer_token()
        self.assertEqual(t1, t2)
        self.assertEqual(mgr.refresh_count, 1)

        fake_time[0] += 32000.0
        t3 = mgr.get_bearer_token()
        self.assertNotEqual(t3, t1)
        self.assertEqual(mgr.refresh_count, 2)

    def test_03_apimatic_idempotency_replay_and_conflict_guard(self) -> None:
        client = APIMaticPayPalClient()
        item = OrderItem("Optic Transceiver", "PHX-800G", 5, Money("USD", "680.00"))
        pu = PurchaseUnitRequest(
            reference_id="Q-905",
            description="5x 800G Optics",
            amount=Money("USD", "3400.00"),
            custom_id="CH3-OPT-800G",
            invoice_id="PO-OPT-100",
            items=[item],
        )
        req = OrderRequest(intent="CAPTURE", purchase_units=[pu])

        first = client.create_order(req, request_id="pp-req-fixed-001")
        self.assertFalse(first["idempotent_replay"])
        self.assertEqual(first["headers_sent"]["PayPal-Request-Id"], "pp-req-fixed-001")

        second = client.create_order(req, request_id="pp-req-fixed-001")
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(second["id"], first["id"])

        mutated_pu = PurchaseUnitRequest(
            reference_id="Q-905",
            description="10x 800G Optics",
            amount=Money("USD", "6800.00"),
            custom_id="CH3-OPT-800G",
            invoice_id="PO-OPT-100",
            items=[OrderItem("Optic Transceiver", "PHX-800G", 10, Money("USD", "680.00"))],
        )
        with self.assertRaisesRegex(APIMaticSchemaValidationError, "Idempotency conflict"):
            client.create_order(OrderRequest(intent="CAPTURE", purchase_units=[mutated_pu]), request_id="pp-req-fixed-001")

    def test_04_paypal_webhook_cryptographic_verification(self) -> None:
        client = APIMaticPayPalClient(webhook_secret="whsec_test_key_2026")
        tx_id = "69cd13f0-d67a-11ef-9912-09a781b2"
        tx_time = "2026-11-10T02:35:10Z"
        wh_id = "WH-2WR32451HC0233532-67976317FL4543714"
        raw_body = '{"event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"CAP-99812"}}'

        sig = client.sign_webhook_event(tx_id, tx_time, wh_id, raw_body)
        valid = client.verify_webhook_signature(tx_id, tx_time, wh_id, raw_body, sig)
        self.assertEqual(valid["verification_status"], "SUCCESS")

        tampered = client.verify_webhook_signature(tx_id, tx_time, wh_id, raw_body + " ", sig)
        self.assertEqual(tampered["verification_status"], "FAILURE")

    def test_05_channel3_catalog_ranking_and_unit_economics(self) -> None:
        treasury = PayPulseAgenticTreasury()
        quotes = treasury.channel3.search_and_rank_quotes(query="H100", quantity=10)
        self.assertEqual(len(quotes), 2)
        top = quotes[0]
        self.assertEqual(top["vendor_name"], "SiliconCloud Direct Corp")
        self.assertAlmostEqual(top["effective_unit_price_usd"], 2598.60)
        self.assertAlmostEqual(top["total_landed_cost_usd"], 25986.00)
        self.assertAlmostEqual(top["negotiated_savings_usd"], 2414.00)
        self.assertGreater(top["channel3_utility_score"], quotes[1]["channel3_utility_score"])

    def test_06_autonomous_procure_3way_match_and_capture(self) -> None:
        treasury = PayPulseAgenticTreasury()
        result = treasury.autonomous_procure(query="H100", quantity=10, auto_capture_if_matched=True)

        self.assertEqual(result["paypal_order"]["status"], "COMPLETED")
        self.assertIn("capture_id", result["paypal_order"])
        self.assertEqual(result["paypal_invoice"]["status"], "SENT")

        ledger_row = result["ag_grid_ledger_entry"]
        self.assertEqual(ledger_row["reconciliation_status"], "MATCHED_VERIFIED")
        self.assertEqual(ledger_row["paypal_settlement_state"], "COMPLETED")
        self.assertEqual(ledger_row["variance_pct"], 0.0)

        sched = result["bryntum_schedule"]
        self.assertEqual(len(sched["tasks"]), 3)
        self.assertEqual(len(sched["dependencies"]), 2)
        self.assertEqual(sched["critical_path_days"], 6)

    def test_07_autonomous_procure_dispute_hold_freezes_escrow(self) -> None:
        treasury = PayPulseAgenticTreasury()
        result = treasury.autonomous_procure(
            query="Telemetry Gateway",
            quantity=10,
            simulated_vendor_invoice_usd=4150.00,
            auto_capture_if_matched=True,
        )

        ledger_row = result["ag_grid_ledger_entry"]
        self.assertEqual(ledger_row["reconciliation_status"], "DISPUTE_HOLD")
        self.assertEqual(ledger_row["paypal_settlement_state"], "ESCROW_FROZEN_BY_AI")
        self.assertGreater(ledger_row["variance_pct"], 1.5)
        self.assertEqual(result["paypal_order"]["status"], "CREATED")

        ag_state = treasury.ag_grid.export_ag_grid_state()
        self.assertEqual(ag_state["kpis"]["dispute_holds_count"], 1)
        self.assertAlmostEqual(ag_state["kpis"]["disputed_volume_protected_usd"], 4150.00)

    def test_08_agentic_tool_dispatcher_and_payout_batch(self) -> None:
        treasury = PayPulseAgenticTreasury()
        schemas = treasury.get_agentic_tool_schemas()
        self.assertEqual(len(schemas), 3)

        payout_res = treasury.execute_agent_tool(
            "paypal_execute_vendor_payout_batch",
            {
                "batch_id": "BATCH-2026-11-10-A",
                "payouts": [
                    {
                        "receiver": "settlements@siliconcloud.io",
                        "amount": "18190.20",
                        "sender_item_id": "ITEM-M3-01",
                        "note": "70% Escrow Milestone Release",
                    },
                    {
                        "receiver": "paypal-receivables@photonix.io",
                        "amount": "6120.00",
                        "sender_item_id": "ITEM-M3-02",
                        "note": "800G Optics Settlement",
                    },
                ],
            },
        )
        self.assertEqual(payout_res["batch_header"]["batch_status"], "SUCCESS")
        self.assertEqual(payout_res["batch_header"]["amount"]["value"], "24310.20")


if __name__ == "__main__":
    unittest.main()
