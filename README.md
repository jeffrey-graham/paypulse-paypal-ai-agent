# PayPulse — Agentic Treasury & Autonomous Procurement OS

**Built for the PayPal AI Hackathon (`$67,500` Prize Pool across 23 Winners)**  
**Live Interactive Command Center:** [https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/](https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/)

![PayPulse Architecture](assets/architecture.png)

## 🎯 Target Tracks & Multi-Sponsor Alignment

PayPulse is engineered from the ground up as a unified autonomous B2B procurement and treasury operating system that qualifies for the **Main Track** (`Best PayPal + AI` & `Best Agentic Commerce`) and all **4 Multi-Winner Sponsor Cash Tracks**:

1. **Main Track — Best PayPal + AI & Best Agentic Commerce (`$12k / $8k / $5k + $5k + $5k`)**:
   - Autonomous AI Procurement Agent exposing MCP/OpenAI-compatible tool definitions (`channel3_search_and_rank_quotes`, `paypal_autonomous_procure_and_schedule`, `paypal_execute_vendor_payout_batch`) backed by **PayPal Orders v2**, **PayPal Invoicing v2**, **PayPal Payouts v1**, and cryptographic **Webhook Signature Verification** (`CRC32` + `HMAC-SHA256`).
2. **Best Use of AG Grid (`$5,000 1st / $2,000 2nd / $1,000 x 3 3rd`)**:
   - Live **AG Grid Enterprise Financial Ledger & 3-Way Match Dispute Grid** (`AGGridLedgerReconciler` + live AG Grid CDN in `index.html`) reconciling Channel3 Purchase Orders against Supplier Invoices and PayPal Captures with instant sorting, quick-filtering, custom variance badges, CSV export, and 1-click dispute resolution.
3. **Best Use of APIMatic (`$1,000 x 3 Winners`)**:
   - Strongly-typed **APIMatic PayPal SDK Client Layer** (`src/apimatic_paypal_sdk.py`) enforcing OpenAPI schema validation (`Money`, `OrderItem`, `PurchaseUnitRequest`, `OrderRequest`, `InvoiceDraftRequest`, `PayoutBatchRequest`), proactive OAuth 2.0 `/v1/oauth2/token` lifecycle caching, and deterministic **`PayPal-Request-Id` Idempotency Middleware** that blocks duplicate captures and detects payload conflicts.
4. **Best Use of Bryntum (`$1,000 x 3 Winners`)**:
   - **Bryntum Settlement Milestone Gantt & Multi-Vendor Escrow Scheduler** (`BryntumSettlementScheduler` + interactive Gantt timeline in `index.html`) modeling Finish-to-Start (`FS`) dependencies (`M1: 30% Order Auth Deposit` ➔ `M2: Carrier Transit & Telemetry QA` ➔ `M3: 3-Way Match & 70% PayPal Capture/Payout`) and 30-day Treasury Liquidity forecasting.
5. **Best Use of Channel3 (`$1,500`)**:
   - **Channel3 AI Product Discovery & Price Intelligence Client** (`Channel3CatalogClient`) querying multi-merchant AI catalogs, applying volume tier discounts, calculating landed unit economics, and ranking vendor quotes by a multi-factor procurement utility score (`50% Price Competitiveness + 30% Merchant Reliability + 20% Lead-Time SLA`).

---

## 🏗️ Repository Structure

```text
paypal-ai-hackathon/
├── index.html                      # Interactive PayPulse Command Center (AG Grid + Bryntum + Channel3 + APIMatic)
├── src/
│   ├── __init__.py
│   ├── apimatic_paypal_sdk.py      # APIMatic Strongly-Typed PayPal SDK, OAuth2, Idempotency & Webhook Verifier
│   └── paypulse_engine.py          # Channel3 Catalog Client, AG Grid 3-Way Reconciler, Bryntum Scheduler & Agentic Tools
├── tests/
│   └── test_paypulse.py            # 8 End-to-End Unit Tests (100% Pass)
├── scripts/
│   └── generate_demo_video.py      # Generates 1080p assets/architecture.png & assets/paypal_ai_demo.mp4
├── assets/
│   ├── architecture.png            # 1080p System Architecture Diagram
│   └── paypal_ai_demo.mp4          # 1080p H.264 Walkthrough Video
├── DEVPOST_SUBMISSION.md           # Complete Devpost Submission Copy
└── README.md
```

---

## 🚀 Quickstart & Verification

### 1. Run the Unit Test Suite
```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```
All 8 tests verify APIMatic schema validation, OAuth2 token lifecycle, `PayPal-Request-Id` idempotency replay & conflict detection, webhook `CRC32` + `HMAC-SHA256` verification, Channel3 quote ranking, 3-Way Match auto-capture vs. dispute freeze (`>1.5%` variance), and Bryntum Finish-to-Start milestone scheduling.

### 2. Launch the Interactive Command Center
Open `index.html` in any browser or visit the live deployment:  
👉 **[https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/](https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/)**
