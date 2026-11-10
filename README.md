# PayPulse — Agentic Treasury & Autonomous Procurement OS

**Built for the PayPal AI Hackathon (`$67,500` Prize Pool across 23 Winners)**  
**Live Interactive Command Center:** [https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/](https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/)

![PayPulse Architecture](assets/architecture.png)

## 🎯 Target Tracks & Multi-Sponsor Alignment

PayPulse is a unified B2B procurement and treasury operating system connecting PayPal's REST APIs with AI catalog intelligence, strongly-typed SDK guardrails, financial ledger reconciliation, and milestone escrow scheduling:

1. **Main Track — Best PayPal + AI & Best Agentic Commerce (`$12k / $8k / $5k + $5k + $5k`)**:
   - Autonomous AI Procurement Agent exposing MCP/OpenAI-compatible tool definitions (`channel3_search_and_rank_quotes`, `paypal_autonomous_procure_and_schedule`, `paypal_execute_vendor_payout_batch`) backed by **PayPal Orders v2**, **PayPal Invoicing v2**, **PayPal Payouts v1**, and cryptographic **Webhook Signature Verification** (`CRC32` + `HMAC-SHA256` local verifier + `/v1/notifications/verify-webhook-signature` live REST verifier).
2. **Best Use of AG Grid (`$5,000 1st / $2,000 2nd / $1,000 x 3 3rd`)**:
   - Live **AG Grid Community v31.3.2 Financial Ledger & 3-Way Match Dispute Grid** (`AGGridLedgerReconciler` + live `ag-grid-community@31.3.2` Quartz Dark grid in `index.html`) reconciling Channel3 Purchase Orders against Supplier Invoices and PayPal Captures with instant sorting, quick-filtering, custom variance badges, CSV export, and 1-click dispute resolution.
3. **Best Use of APIMatic (`$1,000 x 3 Winners`)**:
   - Strongly-typed **APIMatic PayPal SDK Client Layer** (`src/apimatic_paypal_sdk.py`) enforcing OpenAPI schema validation (`Money`, `OrderItem`, `PurchaseUnitRequest`, `OrderRequest`, `InvoiceDraftRequest`, `PayoutBatchRequest`), proactive OAuth 2.0 `/v1/oauth2/token` lifecycle caching, exponential-backoff `RetryPolicy` (`408/429/5xx`), and deterministic **`PayPal-Request-Id` Idempotency Middleware** using canonical JSON SHA-256 fingerprinting.
4. **Best Use of Bryntum (`$1,000 x 3 Winners`)**:
   - **Bryntum Gantt `ProjectModel` Settlement Scheduler** (`BryntumSettlementScheduler.export_bryntum_project_model()` + zero-license-wall browser timeline preview & 1-click JSON export in `index.html`) modeling Finish-to-Start (`FS`) dependencies (`M1: 30% Order Auth Deposit` ➔ `M2: Carrier Transit & Telemetry QA` ➔ `M3: 3-Way Match & 70% PayPal Capture/Payout`) and 30-day Treasury Liquidity forecasting.
5. **Best Use of Channel3 (`$1,500`)**:
   - **Channel3 AI Product Discovery & Price Intelligence Client** (`Channel3CatalogClient`) querying multi-merchant AI catalogs, applying volume tier discounts, calculating landed unit economics, and ranking vendor quotes by a multi-factor procurement utility score (`50% Price Competitiveness + 30% Merchant Reliability + 20% Lead-Time SLA`).

---

## 🔍 Sandbox Simulation vs. Live PayPal REST Mode

To let judges evaluate PayPulse immediately without managing API secrets, PayPulse separates its zero-credential simulation from its implemented PayPal REST HTTP client:

- **Static Browser Command Center (`index.html` on GitHub Pages):** Runs a **zero-credential deterministic client-side simulation** with real **AG Grid Community v31.3.2** rendering/CSV export and interactive **Bryntum `ProjectModel` JSON** generation/export. No PayPal client secrets are embedded in client-side JavaScript.
- **Python SDK & Treasury Engine (`src/apimatic_paypal_sdk.py` + `src/paypulse_engine.py`):** Implements dual-mode transport (`mode="auto" | "live" | "deterministic_sandbox"`):
  - **Deterministic Offline Mode (default when env vars are unset — exercised in CI & unit tests):** Runs reproducible local Order/Invoice/Payout/Webhook state transitions (`transport_mode: "deterministic_sandbox"`).
  - **Live PayPal Sandbox REST Mode (`mode="live"` when `PAYPAL_CLIENT_ID` + `PAYPAL_CLIENT_SECRET` are provided — HTTP transport implemented and unit-tested via injected transport in `tests/test_paypulse.py`; not yet exercised end-to-end against live `api-m.sandbox.paypal.com` credentials):** Exchanges OAuth 2.0 Client Credentials at `/v1/oauth2/token` and dispatches HTTPS requests for Orders v2, Invoicing v2, Payouts v1, and Webhook Verification via stdlib `urllib.request` with `RetryPolicy` exponential backoff (`transport_mode: "live_paypal_rest"`).

---

## 🏗️ Repository Structure

```text
paypal-ai-hackathon/
├── index.html                      # Interactive PayPulse Command Center (AG Grid v31 + Bryntum ProjectModel + Channel3 + APIMatic)
├── src/
│   ├── __init__.py
│   ├── apimatic_paypal_sdk.py      # Dual-Mode APIMatic PayPal SDK, OAuth2, RetryPolicy, Idempotency & Webhook Verifier
│   └── paypulse_engine.py          # Channel3 Catalog Client, AG Grid 3-Way Reconciler, Bryntum Scheduler & CLI Runner
├── tests/
│   └── test_paypulse.py            # 13 Unit & Transport Integration Tests (100% Pass)
├── scripts/
│   └── generate_demo_video.py      # Generates 1080p assets/architecture.png & assets/paypal_ai_demo.mp4
├── assets/
│   ├── architecture.png            # 1080p System Architecture Diagram
│   └── paypal_ai_demo.mp4          # 1080p H.264 Walkthrough Video
├── DEVPOST_SUBMISSION.md           # Devpost Submission Copy
└── README.md
```

---

## 🚀 Quickstart & Verification

### 1. Run the Unit Test Suite (`13/13` Passing)
```bash
PYTHONPATH=. python3 -m unittest discover -s tests -v
```
Verifies APIMatic schema validation, OAuth2 token lifecycle, `PayPal-Request-Id` canonical JSON idempotency replay & conflict detection, live HTTP transport (`Basic` OAuth2 + `Bearer` Orders v2 + Capture), `RetryPolicy` exponential backoff on `429/503`, webhook `CRC32` + `HMAC-SHA256` verification, Channel3 quote ranking, 3-Way Match auto-capture vs. dispute freeze (`>1.5%` variance), and Bryntum `ProjectModel` JSON export.

### 2. Run the End-to-End CLI Demo (Offline Deterministic or Live PayPal Sandbox)
```bash
# Offline deterministic sandbox mode (zero credentials required):
PYTHONPATH=. python3 -m src.paypulse_engine

# Live PayPal Sandbox REST mode:
PAYPAL_CLIENT_ID="your_sandbox_client_id" \
PAYPAL_CLIENT_SECRET="your_sandbox_secret" \
PAYPAL_ENVIRONMENT="sandbox" \
PYTHONPATH=. python3 -m src.paypulse_engine --mode live
```

### 3. Launch the Interactive Command Center
Open `index.html` in any browser or visit the live deployment:  
👉 **[https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/](https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/)**
