"""
PayPulse Agentic Treasury & Autonomous Procurement OS (`paypulse_engine.py`).

Unifies PayPal Agentic Commerce (Orders v2, Invoicing v2, Payouts v1, Webhooks) with:
1. Channel3 AI Product Discovery & Price Intelligence Client (`Channel3CatalogClient`)
2. APIMatic Strongly-Typed PayPal SDK (`APIMaticPayPalClient`)
3. AG Grid Financial Ledger & 3-Way Match Dispute Reconciler (`AGGridLedgerReconciler`)
4. Bryntum Interactive Settlement & Milestone Gantt Scheduler (`BryntumSettlementScheduler`)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.apimatic_paypal_sdk import (
    APIMaticPayPalClient,
    InvoiceDraftRequest,
    Money,
    OrderItem,
    OrderRequest,
    PayoutBatchRequest,
    PayoutRecipientItem,
    PurchaseUnitRequest,
)


@dataclass
class Channel3VendorQuote:
    quote_id: str
    product_id: str
    product_name: str
    category: str
    vendor_name: str
    vendor_paypal_email: str
    sku: str
    base_unit_price_usd: float
    volume_discount_pct: float
    shipping_flat_usd: float
    lead_time_days: int
    reliability_score: float  # 0.0 .. 100.0
    in_stock_qty: int

    def effective_unit_price(self, quantity: int) -> float:
        discount = self.volume_discount_pct if quantity >= 10 else (self.volume_discount_pct * 0.4 if quantity >= 5 else 0.0)
        return round(self.base_unit_price_usd * (1.0 - discount / 100.0), 2)

    def total_landed_cost(self, quantity: int) -> float:
        unit = self.effective_unit_price(quantity)
        return round(unit * quantity + self.shipping_flat_usd, 2)


class Channel3CatalogClient:
    """
    Channel3 AI Product Discovery & Price Intelligence Client.
    Queries multi-merchant AI catalogs, computes unit economics & landed cost,
    and ranks vendor quotes using multi-factor procurement utility scoring.
    """

    def __init__(self) -> None:
        self._catalog: List[Channel3VendorQuote] = [
            Channel3VendorQuote(
                quote_id="CH3-Q-901",
                product_id="CH3-GPU-H100",
                product_name="NVIDIA H100 NVL 94GB PCIe Enterprise AI Accelerator",
                category="AI Infrastructure",
                vendor_name="SiliconCloud Direct Corp",
                vendor_paypal_email="settlements@siliconcloud.io",
                sku="NV-H100-94G-ENT",
                base_unit_price_usd=2840.00,
                volume_discount_pct=8.5,
                shipping_flat_usd=0.00,
                lead_time_days=4,
                reliability_score=98.6,
                in_stock_qty=120,
            ),
            Channel3VendorQuote(
                quote_id="CH3-Q-902",
                product_id="CH3-GPU-H100",
                product_name="NVIDIA H100 NVL 94GB PCIe Enterprise AI Accelerator",
                category="AI Infrastructure",
                vendor_name="Apex Compute Wholesale",
                vendor_paypal_email="ar-paypal@apexcompute.com",
                sku="NV-H100-94G-APX",
                base_unit_price_usd=2950.00,
                volume_discount_pct=5.0,
                shipping_flat_usd=180.00,
                lead_time_days=9,
                reliability_score=91.2,
                in_stock_qty=45,
            ),
            Channel3VendorQuote(
                quote_id="CH3-Q-903",
                product_id="CH3-IOT-GW5",
                product_name="Channel3 Edge AI Industrial Telemetry Gateway v5",
                category="Edge Robotics & IoT",
                vendor_name="NexaGrid Hardware Ltd",
                vendor_paypal_email="treasury@nexagrid.ai",
                sku="NX-IOT-GW5-PRO",
                base_unit_price_usd=420.00,
                volume_discount_pct=12.0,
                shipping_flat_usd=45.00,
                lead_time_days=3,
                reliability_score=97.4,
                in_stock_qty=500,
            ),
            Channel3VendorQuote(
                quote_id="CH3-Q-904",
                product_id="CH3-IOT-GW5",
                product_name="Channel3 Edge AI Industrial Telemetry Gateway v5",
                category="Edge Robotics & IoT",
                vendor_name="Pacific Rim Components",
                vendor_paypal_email="billing@pacrim-comp.net",
                sku="PR-IOT-GW5-STD",
                base_unit_price_usd=445.00,
                volume_discount_pct=6.0,
                shipping_flat_usd=120.00,
                lead_time_days=11,
                reliability_score=88.5,
                in_stock_qty=300,
            ),
            Channel3VendorQuote(
                quote_id="CH3-Q-905",
                product_id="CH3-OPT-800G",
                product_name="800G OSFP DR8 InfiniBand Optical Transceiver Module",
                category="Networking & Optics",
                vendor_name="Photonix Interconnect Inc",
                vendor_paypal_email="paypal-receivables@photonix.io",
                sku="PHX-800G-OSFP",
                base_unit_price_usd=680.00,
                volume_discount_pct=10.0,
                shipping_flat_usd=0.00,
                lead_time_days=2,
                reliability_score=99.1,
                in_stock_qty=800,
            ),
        ]

    def search_and_rank_quotes(
        self,
        query: str,
        quantity: int = 10,
        max_lead_time_days: int = 14,
    ) -> List[Dict[str, Any]]:
        if quantity < 1:
            raise ValueError("quantity must be >= 1")
        q_lower = query.lower().strip()
        matches = [
            q
            for q in self._catalog
            if (
                not q_lower
                or q_lower in q.product_name.lower()
                or q_lower in q.category.lower()
                or q_lower in q.sku.lower()
                or q_lower in q.product_id.lower()
            )
            and q.in_stock_qty >= quantity
            and q.lead_time_days <= max_lead_time_days
        ]
        if not matches:
            return []

        max_cost = max(m.total_landed_cost(quantity) for m in matches)
        min_cost = min(m.total_landed_cost(quantity) for m in matches)
        cost_span = max(1.0, max_cost - min_cost)

        ranked: List[Dict[str, Any]] = []
        for quote in matches:
            landed = quote.total_landed_cost(quantity)
            unit_eff = quote.effective_unit_price(quantity)
            savings_usd = round((quote.base_unit_price_usd * quantity) - (unit_eff * quantity), 2)
            # Multi-factor procurement utility: 50% price competitiveness, 30% merchant reliability, 20% lead-time SLA
            price_score = 100.0 * (1.0 - (landed - min_cost) / cost_span) if max_cost > min_cost else 100.0
            sla_score = max(0.0, 100.0 - (quote.lead_time_days - 1) * 7.5)
            composite_score = round(0.50 * price_score + 0.30 * quote.reliability_score + 0.20 * sla_score, 2)

            ranked.append(
                {
                    "quote_id": quote.quote_id,
                    "product_id": quote.product_id,
                    "product_name": quote.product_name,
                    "category": quote.category,
                    "vendor_name": quote.vendor_name,
                    "vendor_paypal_email": quote.vendor_paypal_email,
                    "sku": quote.sku,
                    "quantity": quantity,
                    "base_unit_price_usd": quote.base_unit_price_usd,
                    "effective_unit_price_usd": unit_eff,
                    "shipping_flat_usd": quote.shipping_flat_usd,
                    "total_landed_cost_usd": landed,
                    "negotiated_savings_usd": savings_usd,
                    "lead_time_days": quote.lead_time_days,
                    "reliability_score": quote.reliability_score,
                    "channel3_utility_score": composite_score,
                }
            )

        ranked.sort(key=lambda r: (-r["channel3_utility_score"], r["total_landed_cost_usd"]))
        return ranked


@dataclass
class BryntumMilestoneTask:
    id: str
    name: str
    vendor: str
    paypal_ref: str
    start_date: str
    end_date: str
    duration_days: int
    percent_done: int
    amount_usd: float
    status: str
    dependencies: List[str] = field(default_factory=list)


class BryntumSettlementScheduler:
    """
    Bryntum-compatible Gantt & Settlement Timeline Scheduler.
    Generates multi-vendor procurement milestones, dependency links (Finish-to-Start),
    and 30-day Treasury Liquidity & Escrow release forecasts.
    """

    def __init__(self) -> None:
        self.tasks: List[BryntumMilestoneTask] = []
        self.dependencies: List[Dict[str, str]] = []

    def schedule_procurement_workflow(
        self,
        order_id: str,
        vendor_name: str,
        total_amount_usd: float,
        lead_time_days: int,
        base_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        anchor = base_date or datetime(2026, 11, 10, tzinfo=timezone.utc)
        t1_id = f"{order_id}-M1"
        t2_id = f"{order_id}-M2"
        t3_id = f"{order_id}-M3"

        d0 = anchor.strftime("%Y-%m-%d")
        d1 = (anchor + timedelta(days=1)).strftime("%Y-%m-%d")
        d2 = (anchor + timedelta(days=1 + max(1, lead_time_days))).strftime("%Y-%m-%d")
        d3 = (anchor + timedelta(days=2 + max(1, lead_time_days))).strftime("%Y-%m-%d")

        deposit_usd = round(total_amount_usd * 0.30, 2)
        escrow_balance_usd = round(total_amount_usd - deposit_usd, 2)

        m1 = BryntumMilestoneTask(
            id=t1_id,
            name="1. Channel3 Quote Lock & PayPal Order Auth (30% Deposit)",
            vendor=vendor_name,
            paypal_ref=order_id,
            start_date=d0,
            end_date=d1,
            duration_days=1,
            percent_done=100,
            amount_usd=deposit_usd,
            status="AUTHORIZED_ESCROW",
            dependencies=[],
        )
        m2 = BryntumMilestoneTask(
            id=t2_id,
            name="2. Carrier Transit & Telemetry QA Inspection",
            vendor=vendor_name,
            paypal_ref=order_id,
            start_date=d1,
            end_date=d2,
            duration_days=max(1, lead_time_days),
            percent_done=60,
            amount_usd=0.0,
            status="IN_TRANSIT_QA",
            dependencies=[t1_id],
        )
        m3 = BryntumMilestoneTask(
            id=t3_id,
            name="3. 3-Way Match Verification & PayPal Capture / Payout (70%)",
            vendor=vendor_name,
            paypal_ref=order_id,
            start_date=d2,
            end_date=d3,
            duration_days=1,
            percent_done=0,
            amount_usd=escrow_balance_usd,
            status="SCHEDULED_RELEASE",
            dependencies=[t2_id],
        )

        self.tasks.extend([m1, m2, m3])
        dep_edges = [
            {"id": f"DEP-{t1_id}-{t2_id}", "fromTask": t1_id, "toTask": t2_id, "type": "FinishToStart"},
            {"id": f"DEP-{t2_id}-{t3_id}", "fromTask": t2_id, "toTask": t3_id, "type": "FinishToStart"},
        ]
        self.dependencies.extend(dep_edges)

        return {
            "order_id": order_id,
            "tasks": [asdict(m1), asdict(m2), asdict(m3)],
            "dependencies": dep_edges,
            "critical_path_days": 2 + max(1, lead_time_days),
        }

    def export_bryntum_project_model(self) -> Dict[str, Any]:
        total_committed = round(sum(t.amount_usd for t in self.tasks), 2)
        return {
            "project": {
                "calendar": "general",
                "startDate": "2026-11-10",
                "hoursPerDay": 24,
                "daysPerWeek": 7,
            },
            "tasks": {"rows": [asdict(t) for t in self.tasks]},
            "dependencies": {"rows": list(self.dependencies)},
            "treasury_summary": {
                "total_scheduled_milestones": len(self.tasks),
                "total_committed_liquidity_usd": total_committed,
            },
        }


class AGGridLedgerReconciler:
    """
    AG Grid Enterprise Financial Ledger & 3-Way Match Dispute Resolution Engine.
    Reconciles Channel3 Purchase Orders against Supplier Invoices and PayPal Orders/Captures.
    Automatically places transactions with > 1.5% variance into `DISPUTE_HOLD`.
    """

    DISPUTE_VARIANCE_THRESHOLD_PCT = 1.5

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    @staticmethod
    def get_column_defs() -> List[Dict[str, Any]]:
        return [
            {"field": "ledger_id", "headerName": "Ledger ID", "sortable": True, "filter": True, "pinned": "left"},
            {"field": "paypal_order_id", "headerName": "PayPal Order ID", "sortable": True, "filter": True},
            {"field": "paypal_request_id", "headerName": "APIMatic Request-Id", "sortable": True, "filter": True},
            {"field": "vendor_name", "headerName": "Channel3 Merchant", "sortable": True, "filter": True},
            {"field": "sku", "headerName": "SKU", "sortable": True, "filter": True},
            {"field": "po_amount_usd", "headerName": "PO Amount ($)", "sortable": True, "type": "numericColumn"},
            {
                "field": "invoice_amount_usd",
                "headerName": "Billed Invoice ($)",
                "sortable": True,
                "type": "numericColumn",
            },
            {"field": "variance_pct", "headerName": "Variance (%)", "sortable": True, "type": "numericColumn"},
            {"field": "reconciliation_status", "headerName": "3-Way Match Status", "sortable": True, "filter": True},
            {"field": "paypal_settlement_state", "headerName": "PayPal State", "sortable": True, "filter": True},
        ]

    def record_and_reconcile(
        self,
        paypal_order_id: str,
        paypal_request_id: str,
        vendor_name: str,
        sku: str,
        quantity: int,
        po_amount_usd: float,
        invoice_amount_usd: float,
        paypal_settlement_state: str,
    ) -> Dict[str, Any]:
        variance_usd = round(invoice_amount_usd - po_amount_usd, 2)
        variance_pct = round((abs(variance_usd) / max(0.01, po_amount_usd)) * 100.0, 2)

        if variance_pct > self.DISPUTE_VARIANCE_THRESHOLD_PCT:
            reconciliation_status = "DISPUTE_HOLD"
            effective_settlement = "ESCROW_FROZEN_BY_AI"
            recommended_action = (
                f"Hold PayPal capture: Invoice exceeds Channel3 PO by ${variance_usd:.2f} ({variance_pct:.2f}%)"
            )
        else:
            reconciliation_status = "MATCHED_VERIFIED"
            effective_settlement = paypal_settlement_state
            recommended_action = "Auto-approve PayPal capture & release milestone payout"

        row = {
            "ledger_id": f"LDG-{1000 + len(self.rows) + 1}",
            "paypal_order_id": paypal_order_id,
            "paypal_request_id": paypal_request_id,
            "vendor_name": vendor_name,
            "sku": sku,
            "quantity": quantity,
            "po_amount_usd": round(po_amount_usd, 2),
            "invoice_amount_usd": round(invoice_amount_usd, 2),
            "variance_usd": variance_usd,
            "variance_pct": variance_pct,
            "reconciliation_status": reconciliation_status,
            "paypal_settlement_state": effective_settlement,
            "recommended_action": recommended_action,
        }
        self.rows.append(row)
        return row

    def export_ag_grid_state(self) -> Dict[str, Any]:
        total_po = round(sum(r["po_amount_usd"] for r in self.rows), 2)
        disputed = [r for r in self.rows if r["reconciliation_status"] == "DISPUTE_HOLD"]
        return {
            "columnDefs": self.get_column_defs(),
            "rowData": list(self.rows),
            "kpis": {
                "total_transactions": len(self.rows),
                "total_po_volume_usd": total_po,
                "dispute_holds_count": len(disputed),
                "disputed_volume_protected_usd": round(sum(r["invoice_amount_usd"] for r in disputed), 2),
            },
        }


class PayPulseAgenticTreasury:
    """
    Master Autonomous Procurement & Treasury Agent orchestrating:
    - Channel3 Catalog Discovery & Price Intelligence
    - APIMatic Strongly-Typed PayPal Orders v2, Invoicing v2, Payouts v1 & Webhooks
    - AG Grid 3-Way Match Financial Ledger & Dispute Blocker
    - Bryntum Milestone Gantt & Cash-Flow Scheduler
    """

    def __init__(self, sdk_client: Optional[APIMaticPayPalClient] = None) -> None:
        self.sdk = sdk_client or APIMaticPayPalClient()
        self.channel3 = Channel3CatalogClient()
        self.ag_grid = AGGridLedgerReconciler()
        self.bryntum = BryntumSettlementScheduler()

    @staticmethod
    def get_agentic_tool_schemas() -> List[Dict[str, Any]]:
        """Returns PayPal Agentic Commerce / MCP compatible tool schemas."""
        return [
            {
                "name": "channel3_search_and_rank_quotes",
                "description": "Search Channel3 AI product catalogs and rank vendor quotes by landed unit economics, reliability, and SLA.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "max_lead_time_days": {"type": "integer", "minimum": 1},
                    },
                    "required": ["query", "quantity"],
                },
            },
            {
                "name": "paypal_autonomous_procure_and_schedule",
                "description": "Execute end-to-end autonomous procurement via APIMatic PayPal SDK, reconcile in AG Grid ledger, and schedule Bryntum escrow milestones.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "quantity": {"type": "integer", "minimum": 1},
                        "simulated_vendor_invoice_usd": {"type": "number"},
                        "auto_capture_if_matched": {"type": "boolean"},
                    },
                    "required": ["query", "quantity"],
                },
            },
            {
                "name": "paypal_execute_vendor_payout_batch",
                "description": "Disburse multi-vendor milestone settlements via PayPal Payouts v1 API with APIMatic idempotency enforcement.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "batch_id": {"type": "string"},
                        "payouts": {"type": "array"},
                    },
                    "required": ["batch_id", "payouts"],
                },
            },
        ]

    def autonomous_procure(
        self,
        query: str,
        quantity: int = 10,
        simulated_vendor_invoice_usd: Optional[float] = None,
        auto_capture_if_matched: bool = True,
    ) -> Dict[str, Any]:
        quotes = self.channel3.search_and_rank_quotes(query=query, quantity=quantity)
        if not quotes:
            raise ValueError(f"No Channel3 vendor quotes matched query='{query}' for quantity={quantity}")

        best = quotes[0]
        unit_money = Money(currency_code="USD", value=f"{best['effective_unit_price_usd']:.2f}")
        item_subtotal = round(best["effective_unit_price_usd"] * quantity, 2)
        po_number = f"PO-CH3-{best['quote_id']}-{quantity}"

        order_item = OrderItem(
            name=best["product_name"],
            sku=best["sku"],
            quantity=quantity,
            unit_amount=unit_money,
        )
        pu = PurchaseUnitRequest(
            reference_id=best["quote_id"],
            description=f"Channel3 Autonomous Procurement: {quantity}x {best['product_name']}",
            amount=Money(currency_code="USD", value=f"{item_subtotal:.2f}"),
            custom_id=best["product_id"],
            invoice_id=po_number,
            items=[order_item],
            payee_email=best["vendor_paypal_email"],
        )
        order_req = OrderRequest(
            intent="CAPTURE" if auto_capture_if_matched else "AUTHORIZE",
            purchase_units=[pu],
        )

        created_order = self.sdk.create_order(order_req)
        order_id = created_order["id"]
        req_id = created_order["paypal_request_id"]

        # Create corresponding PayPal Invoice v2 record
        inv_req = InvoiceDraftRequest(
            invoice_number=f"INV-{po_number}",
            recipient_email="ap-treasury@paypulse.enterprise.ai",
            recipient_business_name="PayPulse Enterprise Treasury Corp",
            items=[order_item],
        )
        invoice_res = self.sdk.create_and_send_invoice(inv_req)

        billed_usd = simulated_vendor_invoice_usd if simulated_vendor_invoice_usd is not None else item_subtotal
        initial_state = "CREATED"

        # 3-Way Match Reconciliation in AG Grid Ledger
        ledger_row = self.ag_grid.record_and_reconcile(
            paypal_order_id=order_id,
            paypal_request_id=req_id,
            vendor_name=best["vendor_name"],
            sku=best["sku"],
            quantity=quantity,
            po_amount_usd=item_subtotal,
            invoice_amount_usd=billed_usd,
            paypal_settlement_state=initial_state,
        )

        # Only capture if 3-Way Match succeeded without dispute hold
        settlement_result = created_order
        if ledger_row["reconciliation_status"] == "MATCHED_VERIFIED":
            if auto_capture_if_matched:
                settlement_result = self.sdk.capture_order(order_id)
                ledger_row["paypal_settlement_state"] = "COMPLETED"
            else:
                settlement_result = self.sdk.authorize_order(order_id)
                ledger_row["paypal_settlement_state"] = "AUTHORIZED"

        # Schedule Bryntum Milestone Gantt tasks
        bryntum_schedule = self.bryntum.schedule_procurement_workflow(
            order_id=order_id,
            vendor_name=best["vendor_name"],
            total_amount_usd=item_subtotal,
            lead_time_days=best["lead_time_days"],
        )

        return {
            "selected_channel3_quote": best,
            "alternative_quotes_evaluated": len(quotes),
            "paypal_order": settlement_result,
            "paypal_invoice": invoice_res,
            "ag_grid_ledger_entry": ledger_row,
            "bryntum_schedule": bryntum_schedule,
        }

    def execute_agent_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if tool_name == "channel3_search_and_rank_quotes":
            return {
                "quotes": self.channel3.search_and_rank_quotes(
                    query=arguments["query"],
                    quantity=int(arguments.get("quantity", 10)),
                    max_lead_time_days=int(arguments.get("max_lead_time_days", 14)),
                )
            }
        if tool_name == "paypal_autonomous_procure_and_schedule":
            return self.autonomous_procure(
                query=arguments["query"],
                quantity=int(arguments.get("quantity", 10)),
                simulated_vendor_invoice_usd=arguments.get("simulated_vendor_invoice_usd"),
                auto_capture_if_matched=bool(arguments.get("auto_capture_if_matched", True)),
            )
        if tool_name == "paypal_execute_vendor_payout_batch":
            items = [
                PayoutRecipientItem(
                    receiver=item["receiver"],
                    amount=Money(currency_code=item.get("currency", "USD"), value=f"{float(item['amount']):.2f}"),
                    sender_item_id=item["sender_item_id"],
                    note=item.get("note", "PayPulse Bryntum Milestone Payout"),
                )
                for item in arguments["payouts"]
            ]
            batch_req = PayoutBatchRequest(
                sender_batch_id=arguments["batch_id"],
                email_subject="PayPulse Autonomous Milestone Escrow Payout",
                email_message="Your verified Channel3 procurement milestone has been settled via PayPal Payouts.",
                items=items,
            )
            return self.sdk.create_payout_batch(batch_req)
        raise ValueError(f"Unsupported PayPulse agentic tool: '{tool_name}'")
