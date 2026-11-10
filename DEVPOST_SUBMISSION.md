# Devpost Submission — PayPal AI Hackathon

## Project Title
**PayPulse — Agentic Treasury & Autonomous Procurement OS (PayPal AI + AG Grid + Bryntum + APIMatic + Channel3)**

## Tagline
Autonomous B2B procurement & escrow settlement OS uniting PayPal Agentic Commerce (Orders v2, Invoicing v2, Payouts v1), Channel3 AI sourcing, APIMatic typed SDKs, AG Grid 3-way match ledgers, and Bryntum milestone Gantt scheduling.

## Live Links
- **Live Interactive Web App (GitHub Pages):** https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/
- **Public GitHub Repository:** https://github.com/jeffrey-graham/paypulse-paypal-ai-agent
- **Demo Video:** `assets/paypal_ai_demo.mp4`

---

## 💡 Inspiration
Enterprise procurement and accounts-payable teams lose billions annually to fragmented vendor discovery, manual purchase-order-to-invoice reconciliation, duplicate payment retries, and premature escrow releases before goods pass quality inspection. While AI agents can now browse catalogs, giving an autonomous agent direct access to corporate payment rails requires **strict schema validation, deterministic idempotency (`PayPal-Request-Id`), automated 3-way match dispute protection, and milestone-gated liquidity scheduling**.

We built **PayPulse** to bridge that exact gap: an end-to-end Agentic Treasury & Autonomous Procurement OS powered by **PayPal REST APIs**, **Channel3**, **APIMatic**, **AG Grid**, and **Bryntum**.

---

## ⚙️ What It Does
1. **Channel3 AI Product Discovery & Unit Economics Ranking (`Channel3CatalogClient`)**:
   - Queries multi-merchant AI hardware and IoT catalogs, applies volume-tier discounts, calculates total landed cost (unit price + shipping), and ranks competing vendor quotes using a weighted utility model (**50% Price Competitiveness, 30% Merchant Reliability, 20% Lead-Time SLA**).
2. **APIMatic Strongly-Typed PayPal SDK (`APIMaticPayPalClient`)**:
   - Wraps **PayPal Orders v2** (`/v2/checkout/orders`, `/authorize`, `/capture`), **Invoicing v2** (`/v2/invoicing/invoices`), and **Payouts v1** (`/v1/payments/payouts`) inside strongly-typed OpenAPI schema validators (`Money`, `OrderItem`, `PurchaseUnitRequest`, `OrderRequest`, `InvoiceDraftRequest`, `PayoutBatchRequest`).
   - Enforces automatic OAuth 2.0 `/v1/oauth2/token` lifecycle caching and deterministic **`PayPal-Request-Id` Idempotency Middleware** (`IdempotencyMiddleware`) that suppresses duplicate captures on network retries and raises immediate schema conflict alerts if a request ID is reused with a mutated payload.
   - Verifies incoming PayPal webhooks via cryptographic **CRC32 + HMAC-SHA256** signature validation.
3. **AG Grid v31 Financial Ledger & 3-Way Match Dispute Engine (`AGGridLedgerReconciler`)**:
   - Performs automated 3-way matching across the **Channel3 Purchase Order**, **Supplier Invoice**, and **PayPal Settlement State**.
   - If invoice variance is `<= 1.5%`, PayPulse automatically captures the PayPal order (`COMPLETED`).
   - If a supplier submits an inflated invoice (`> 1.5%` variance), PayPulse immediately freezes the transaction in **`DISPUTE_HOLD` (`ESCROW_FROZEN_BY_AI`)** inside the live **AG Grid Community v31.3.2** command center, allowing finance operators to filter, inspect, export CSVs, or resolve disputes in one click.
4. **Bryntum `ProjectModel` Settlement Milestone Gantt Scheduler (`BryntumSettlementScheduler`)**:
   - Automatically generates a structured Bryntum Gantt `ProjectModel` JSON (`project`, `tasks.rows`, and 3-stage **Finish-to-Start (`FS`)** `dependencies.rows`) for every procurement order, rendered in an embedded zero-license-wall browser timeline with 1-click `ProjectModel` JSON export:
     - `M1`: Channel3 Quote Lock & 30% PayPal Order Authorization Deposit
     - `M2`: Carrier Transit & Telemetry QA Inspection Window
     - `M3`: 3-Way Match Verification & 70% PayPal Capture / Payouts v1 Batch Release

---

## 🏆 Sponsor Track Qualification Summary
- **Main Track (Best PayPal + AI & Best Agentic Commerce):** Full MCP/Function-Calling tool suite orchestrating PayPal Orders v2, Invoicing v2, Payouts v1, and cryptographic webhook verification (`mode="live"` HTTPS against `api-m.sandbox.paypal.com` via `PAYPAL_CLIENT_ID`/`SECRET` + deterministic zero-credential sandbox fallback).
- **Best Use of AG Grid:** Live interactive AG Grid Community v31.3.2 financial ledger with custom status & variance cell renderers, quick-search filtering, column sorting, one-click dispute resolution, and CSV export.
- **Best Use of APIMatic:** Strongly-typed SDK architecture with pre-flight schema validation, OAuth2 token lifecycle management, exponential backoff retry policy (`408/429/5xx`), and canonical-JSON `PayPal-Request-Id` idempotency replay protection.
- **Best Use of Bryntum:** Structured Bryntum Gantt `ProjectModel` JSON generator (`tasks` + Finish-to-Start `dependencies`) paired with an interactive milestone Gantt timeline and 1-click JSON export.
- **Best Use of Channel3:** Multi-merchant AI product discovery and unit-economics price intelligence engine that negotiates volume discounts ($2,414 saved on a single 10x H100 order) and feeds directly into PayPal Order creation.
