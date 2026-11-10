"""
APIMatic Strongly-Typed PayPal REST SDK Client Layer (`apimatic_paypal_sdk.py`).

Architected following APIMatic CodeGen patterns for PayPal REST APIs with dual-mode transport:
- Strictly validated Request/Response data models (`Money`, `PurchaseUnitRequest`,
  `OrderRequest`, `InvoiceDraftRequest`, `PayoutBatchRequest`)
- Dual-mode HTTP transport (`mode="auto" | "live" | "deterministic_sandbox"`):
  * Executes live HTTPS requests against `https://api-m.sandbox.paypal.com` (or live PayPal)
    using Python stdlib `urllib.request` when `PAYPAL_CLIENT_ID` & `PAYPAL_CLIENT_SECRET`
    are set (or when `mode="live"` / custom `http_transport` is supplied).
  * Falls back cleanly to deterministic offline sandbox simulation when credentials are
    absent so unit tests and zero-credential evaluations run reproducibly.
- Automatic OAuth 2.0 Client Credentials token lifecycle management (`/v1/oauth2/token`)
  with proactive pre-expiry refresh
- Deterministic Idempotency Middleware enforcing `PayPal-Request-Id` header generation,
  canonical JSON payload fingerprinting, and replay/conflict protection cache
- Exponential backoff retry policy (`RetryPolicy`) for transient 408/429/5xx responses
- Cryptographic PayPal Webhook Signature Verification (`CRC32` + HMAC-SHA256 local verifier
  and `/v1/notifications/verify-webhook-signature` live REST verifier)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple


class APIMaticSchemaValidationError(ValueError):
    """Raised when a request or response model violates APIMatic OpenAPI schema constraints."""


class APIMaticAuthError(PermissionError):
    """Raised when OAuth2 token acquisition or webhook signature verification fails."""


class APIMaticHTTPError(RuntimeError):
    """Raised when PayPal REST API returns a non-retryable error or exhausts retry attempts."""

    def __init__(self, status_code: int, message: str, response_body: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(f"PayPal HTTP {status_code}: {message}")
        self.status_code = status_code
        self.response_body = response_body or {}


HttpTransportCallable = Callable[[str, str, Dict[str, str], Optional[bytes]], Tuple[int, Dict[str, Any]]]

SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "SGD"}
VALID_ORDER_INTENTS = {"CAPTURE", "AUTHORIZE"}
DEFAULT_DEMO_CLIENT_ID = "PAYPULSE_SANDBOX_CLIENT_ID_2026"
DEFAULT_DEMO_CLIENT_SECRET = "PAYPULSE_SANDBOX_SECRET_99481"


def canonical_json_fingerprint(payload: Any) -> str:
    """Produces a key-order-independent SHA-256 hex digest for idempotency verification."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def stdlib_urllib_transport(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes] = None,
    timeout_sec: float = 15.0,
) -> Tuple[int, Dict[str, Any]]:
    """Executes an HTTPS request against PayPal REST endpoints using Python stdlib `urllib`."""
    req = urllib.request.Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw.strip() else {}
            return int(resp.status), parsed
    except urllib.error.HTTPError as exc:
        raw_err = exc.read().decode("utf-8", errors="replace")
        try:
            parsed_err = json.loads(raw_err) if raw_err.strip() else {"message": str(exc)}
        except json.JSONDecodeError:
            parsed_err = {"message": raw_err or str(exc)}
        return int(exc.code), parsed_err


@dataclass(frozen=True)
class Money:
    currency_code: str
    value: str

    def validate(self) -> None:
        if self.currency_code not in SUPPORTED_CURRENCIES:
            raise APIMaticSchemaValidationError(
                f"Unsupported currency_code '{self.currency_code}'. Must be one of {sorted(SUPPORTED_CURRENCIES)}"
            )
        try:
            numeric = float(self.value)
        except ValueError as exc:
            raise APIMaticSchemaValidationError(f"Invalid monetary value '{self.value}'") from exc
        if numeric <= 0:
            raise APIMaticSchemaValidationError(f"Monetary value must be > 0, got {numeric}")
        if self.currency_code != "JPY" and "." in self.value:
            decimals = len(self.value.split(".")[1])
            if decimals > 2:
                raise APIMaticSchemaValidationError(
                    f"Currency {self.currency_code} allows at most 2 decimal places, got '{self.value}'"
                )

    def to_dict(self) -> Dict[str, str]:
        self.validate()
        if self.currency_code == "JPY":
            return {"currency_code": self.currency_code, "value": f"{int(round(float(self.value)))}"}
        return {"currency_code": self.currency_code, "value": f"{float(self.value):.2f}"}


@dataclass
class OrderItem:
    name: str
    sku: str
    quantity: int
    unit_amount: Money
    category: str = "PHYSICAL_GOODS"

    def validate(self) -> None:
        if not self.name or len(self.name) > 127:
            raise APIMaticSchemaValidationError("OrderItem.name must be 1..127 characters")
        if self.quantity < 1:
            raise APIMaticSchemaValidationError("OrderItem.quantity must be >= 1")
        self.unit_amount.validate()

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "name": self.name,
            "sku": self.sku,
            "quantity": str(self.quantity),
            "unit_amount": self.unit_amount.to_dict(),
            "category": self.category,
        }


@dataclass
class PurchaseUnitRequest:
    reference_id: str
    description: str
    amount: Money
    custom_id: str
    invoice_id: str
    items: List[OrderItem] = field(default_factory=list)
    payee_email: Optional[str] = None

    def validate(self) -> None:
        if not self.reference_id or len(self.reference_id) > 256:
            raise APIMaticSchemaValidationError("PurchaseUnitRequest.reference_id is required (1..256 chars)")
        self.amount.validate()
        if self.items:
            item_total = sum(float(i.unit_amount.value) * i.quantity for i in self.items)
            for item in self.items:
                item.validate()
            declared = float(self.amount.value)
            if abs(item_total - declared) > 0.01:
                raise APIMaticSchemaValidationError(
                    f"PurchaseUnit amount ({declared:.2f}) does not match sum of items ({item_total:.2f})"
                )

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        payload: Dict[str, Any] = {
            "reference_id": self.reference_id,
            "description": self.description,
            "custom_id": self.custom_id,
            "invoice_id": self.invoice_id,
            "amount": {
                **self.amount.to_dict(),
                "breakdown": {
                    "item_total": self.amount.to_dict(),
                },
            },
        }
        if self.items:
            payload["items"] = [i.to_dict() for i in self.items]
        if self.payee_email:
            payload["payee"] = {"email_address": self.payee_email}
        return payload


@dataclass
class OrderRequest:
    intent: str
    purchase_units: List[PurchaseUnitRequest]
    return_url: str = "https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/?status=approved"
    cancel_url: str = "https://jeffrey-graham.github.io/paypulse-paypal-ai-agent/?status=cancelled"

    def validate(self) -> None:
        if self.intent not in VALID_ORDER_INTENTS:
            raise APIMaticSchemaValidationError(f"Order intent must be one of {VALID_ORDER_INTENTS}")
        if not self.purchase_units:
            raise APIMaticSchemaValidationError("OrderRequest requires at least one PurchaseUnitRequest")
        for pu in self.purchase_units:
            pu.validate()

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "intent": self.intent,
            "purchase_units": [pu.to_dict() for pu in self.purchase_units],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "brand_name": "PayPulse Autonomous Treasury OS",
                        "locale": "en-US",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "return_url": self.return_url,
                        "cancel_url": self.cancel_url,
                    }
                }
            },
        }


@dataclass
class InvoiceDraftRequest:
    invoice_number: str
    recipient_email: str
    recipient_business_name: str
    items: List[OrderItem]
    payment_term_type: str = "NET_30"
    note: str = "Generated autonomously by PayPulse AI Treasury via APIMatic SDK"

    def validate(self) -> None:
        if not self.invoice_number:
            raise APIMaticSchemaValidationError("invoice_number is required")
        if "@" not in self.recipient_email:
            raise APIMaticSchemaValidationError(f"Invalid recipient_email '{self.recipient_email}'")
        if not self.items:
            raise APIMaticSchemaValidationError("InvoiceDraftRequest must include at least one item")
        for item in self.items:
            item.validate()

    def total_amount(self) -> Money:
        self.validate()
        currency = self.items[0].unit_amount.currency_code
        total = sum(float(i.unit_amount.value) * i.quantity for i in self.items)
        return Money(currency_code=currency, value=f"{total:.2f}")

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "detail": {
                "invoice_number": self.invoice_number,
                "currency_code": self.items[0].unit_amount.currency_code,
                "note": self.note,
                "payment_term": {"term_type": self.payment_term_type},
            },
            "primary_recipients": [
                {
                    "billing_info": {
                        "business_name": self.recipient_business_name,
                        "email_address": self.recipient_email,
                    }
                }
            ],
            "items": [
                {
                    "name": item.name,
                    "description": f"SKU: {item.sku}",
                    "quantity": str(item.quantity),
                    "unit_amount": item.unit_amount.to_dict(),
                }
                for item in self.items
            ],
        }


@dataclass
class PayoutRecipientItem:
    receiver: str
    amount: Money
    sender_item_id: str
    note: str
    recipient_type: str = "EMAIL"

    def validate(self) -> None:
        if "@" not in self.receiver and self.recipient_type == "EMAIL":
            raise APIMaticSchemaValidationError(f"Invalid receiver email '{self.receiver}'")
        if not self.sender_item_id:
            raise APIMaticSchemaValidationError("sender_item_id is required")
        self.amount.validate()

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "recipient_type": self.recipient_type,
            "amount": self.amount.to_dict(),
            "note": self.note,
            "sender_item_id": self.sender_item_id,
            "receiver": self.receiver,
        }


@dataclass
class PayoutBatchRequest:
    sender_batch_id: str
    email_subject: str
    email_message: str
    items: List[PayoutRecipientItem]

    def validate(self) -> None:
        if not self.sender_batch_id:
            raise APIMaticSchemaValidationError("sender_batch_id is required")
        if not self.items:
            raise APIMaticSchemaValidationError("PayoutBatchRequest requires at least 1 PayoutRecipientItem")
        seen_ids = set()
        for item in self.items:
            item.validate()
            if item.sender_item_id in seen_ids:
                raise APIMaticSchemaValidationError(f"Duplicate sender_item_id '{item.sender_item_id}' in batch")
            seen_ids.add(item.sender_item_id)

    def to_dict(self) -> Dict[str, Any]:
        self.validate()
        return {
            "sender_batch_header": {
                "sender_batch_id": self.sender_batch_id,
                "email_subject": self.email_subject,
                "email_message": self.email_message,
            },
            "items": [i.to_dict() for i in self.items],
        }


@dataclass
class RetryPolicy:
    max_retries: int = 3
    backoff_factor: float = 0.25
    retry_status_codes: Tuple[int, ...] = (408, 429, 500, 502, 503, 504)
    sleeper: Callable[[float], None] = time.sleep

    def compute_delay(self, attempt: int) -> float:
        return self.backoff_factor * (2 ** max(0, attempt - 1))

    def execute(self, operation: Callable[[], Tuple[int, Dict[str, Any]]]) -> Tuple[int, Dict[str, Any], int]:
        """
        Executes `operation` with exponential backoff on `retry_status_codes`.
        Returns `(status_code, payload, attempts_made)`.
        """
        attempts = 0
        while True:
            attempts += 1
            status_code, payload = operation()
            if 200 <= status_code < 300:
                return status_code, payload, attempts
            if status_code in self.retry_status_codes and attempts <= self.max_retries:
                self.sleeper(self.compute_delay(attempts))
                continue
            msg = str(payload.get("message") or payload.get("error_description") or f"HTTP {status_code}")
            raise APIMaticHTTPError(status_code=status_code, message=msg, response_body=payload)


class OAuth2TokenManager:
    """
    Manages PayPal `/v1/oauth2/token` bearer tokens with proactive TTL refresh.
    Supports both live HTTP Client Credentials exchange and deterministic offline sandbox mode.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        clock: Callable[[], float] = time.time,
        base_url: str = "https://api-m.sandbox.paypal.com",
        live_http: bool = False,
        http_transport: Optional[HttpTransportCallable] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        if not client_id or not client_secret:
            raise APIMaticAuthError("client_id and client_secret must be non-empty")
        self.client_id = client_id
        self.client_secret = client_secret
        self._clock = clock
        self.base_url = base_url.rstrip("/")
        self.live_http = live_http
        self._transport = http_transport or stdlib_urllib_transport
        self._retry_policy = retry_policy or RetryPolicy()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self.refresh_count: int = 0

    def get_bearer_token(self, force_refresh: bool = False) -> str:
        now = self._clock()
        if force_refresh or not self._access_token or now >= (self._expires_at - 60.0):
            if self.live_http:
                basic_raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
                basic_b64 = base64.b64encode(basic_raw).decode("ascii")
                headers = {
                    "Authorization": f"Basic {basic_b64}",
                    "Accept": "application/json",
                    "Accept-Language": "en_US",
                    "Content-Type": "application/x-www-form-urlencoded",
                }
                form_body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
                try:
                    _, data, _ = self._retry_policy.execute(
                        lambda: self._transport("POST", f"{self.base_url}/v1/oauth2/token", headers, form_body)
                    )
                except APIMaticHTTPError as exc:
                    raise APIMaticAuthError(f"OAuth2 token request failed ({exc.status_code}): {exc}") from exc
                token = data.get("access_token")
                if not token:
                    raise APIMaticAuthError("PayPal OAuth2 response missing 'access_token'")
                ttl = float(data.get("expires_in", 32400.0))
                self._access_token = str(token)
                self._expires_at = now + ttl
            else:
                digest = hashlib.sha256(
                    f"{self.client_id}:{self.client_secret}:{self.refresh_count}".encode("utf-8")
                ).hexdigest()
                self._access_token = f"A21AA_{digest[:36]}"
                self._expires_at = now + 32400.0  # 9 hours standard PayPal OAuth2 TTL
            self.refresh_count += 1
        return self._access_token


class IdempotencyMiddleware:
    """
    APIMatic Idempotency Layer enforcing `PayPal-Request-Id` on all mutating POST calls.
    Prevents duplicate captures, double orders, or duplicate payouts during network retries.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def derive_request_id(operation: str, unique_seed: str) -> str:
        digest = hashlib.sha256(f"{operation}:{unique_seed}".encode("utf-8")).hexdigest()[:24]
        return f"pp-req-{operation.lower()}-{digest}"

    def execute_idempotent(
        self,
        request_id: str,
        payload_fingerprint: str,
        producer: Callable[[], Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not request_id or len(request_id) > 128:
            raise APIMaticSchemaValidationError("PayPal-Request-Id must be 1..128 characters")
        if request_id in self._cache:
            cached = self._cache[request_id]
            if cached["fingerprint"] != payload_fingerprint:
                raise APIMaticSchemaValidationError(
                    f"Idempotency conflict: PayPal-Request-Id '{request_id}' reused with mutated payload"
                )
            response_copy = dict(cached["response"])
            response_copy["idempotent_replay"] = True
            return response_copy

        result = producer()
        result["paypal_request_id"] = request_id
        result["idempotent_replay"] = False
        self._cache[request_id] = {
            "fingerprint": payload_fingerprint,
            "response": dict(result),
        }
        return result


class APIMaticPayPalClient:
    """
    Unified APIMatic-architected SDK Client for PayPal Orders v2, Invoicing v2,
    Payouts v1, and Cryptographic Webhook Verification.

    Transport Modes (`mode` parameter):
    - `"auto"` (default): Uses live PayPal HTTPS REST calls if `PAYPAL_CLIENT_ID` and
      `PAYPAL_CLIENT_SECRET` environment variables are present (or `http_transport` is
      provided); otherwise runs deterministic offline sandbox simulation.
    - `"live"`: Enforces real HTTPS requests to `base_url` via `http_transport` / `urllib`.
    - `"deterministic_sandbox"`: Always uses deterministic in-memory sandbox simulation.
    """

    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        environment: Optional[str] = None,
        webhook_secret: str = "whsec_paypulse_agentic_2026",
        mode: str = "auto",
        http_transport: Optional[HttpTransportCallable] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        env_cid = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
        env_sec = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
        resolved_env = (environment or os.environ.get("PAYPAL_ENVIRONMENT") or "sandbox").strip().lower()
        if mode not in {"auto", "live", "deterministic_sandbox"}:
            raise ValueError(f"Unsupported mode '{mode}'. Choose 'auto', 'live', or 'deterministic_sandbox'.")

        has_env_creds = bool(env_cid and env_sec)
        if mode == "live":
            use_live_http = True
        elif mode == "deterministic_sandbox":
            use_live_http = False
        else:
            use_live_http = bool(http_transport is not None or has_env_creds)

        resolved_cid = client_id if client_id is not None else (env_cid or DEFAULT_DEMO_CLIENT_ID)
        resolved_sec = client_secret if client_secret is not None else (env_sec or DEFAULT_DEMO_CLIENT_SECRET)

        self.environment = resolved_env
        self.transport_mode = "live_paypal_rest" if use_live_http else "deterministic_sandbox"
        self.live_http = use_live_http
        self.base_url = (
            "https://api-m.sandbox.paypal.com"
            if resolved_env == "sandbox"
            else "https://api-m.paypal.com"
        )
        self.webhook_secret = webhook_secret
        self.retry_policy = retry_policy or RetryPolicy()
        self._transport: HttpTransportCallable = http_transport or stdlib_urllib_transport
        self.token_manager = OAuth2TokenManager(
            resolved_cid,
            resolved_sec,
            base_url=self.base_url,
            live_http=use_live_http,
            http_transport=self._transport,
            retry_policy=self.retry_policy,
        )
        self.idempotency = IdempotencyMiddleware()
        self._orders_store: Dict[str, Dict[str, Any]] = {}
        self._invoices_store: Dict[str, Dict[str, Any]] = {}
        self._payouts_store: Dict[str, Dict[str, Any]] = {}
        self.telemetry_log: List[Dict[str, Any]] = []

    def _headers(self, request_id: str) -> Dict[str, str]:
        token = self.token_manager.get_bearer_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Prefer": "return=representation",
            "PayPal-Request-Id": request_id,
            "User-Agent": "APIMatic-PayPulse-SDK/2.5.0 (Python/3.11; AgenticCommerce)",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        request_id: str,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, Dict[str, Any], Dict[str, str], int]:
        headers = self._headers(request_id)
        encoded = json.dumps(json_body).encode("utf-8") if json_body is not None else b"{}"
        url = f"{self.base_url}{path}"
        status_code, data, attempts = self.retry_policy.execute(
            lambda: self._transport(method, url, headers, encoded)
        )
        return status_code, data, headers, attempts

    def create_order(self, order_req: OrderRequest, request_id: Optional[str] = None) -> Dict[str, Any]:
        body = order_req.to_dict()
        pu0 = order_req.purchase_units[0]
        req_id = request_id or self.idempotency.derive_request_id("create-order", pu0.invoice_id)
        fingerprint = canonical_json_fingerprint(body)

        def _produce() -> Dict[str, Any]:
            if self.live_http:
                status_code, data, headers, attempts = self._request_json(
                    "POST", "/v2/checkout/orders", req_id, body
                )
                order_id = str(data.get("id") or f"ORD-{hashlib.sha1(req_id.encode()).hexdigest()[:12].upper()}")
                record = {
                    **data,
                    "id": order_id,
                    "intent": data.get("intent", order_req.intent),
                    "status": data.get("status", "CREATED"),
                    "purchase_units": data.get("purchase_units", body["purchase_units"]),
                    "transport_mode": self.transport_mode,
                    "headers_sent": {
                        "PayPal-Request-Id": headers["PayPal-Request-Id"],
                        "User-Agent": headers["User-Agent"],
                    },
                }
            else:
                headers = self._headers(req_id)
                status_code, attempts = 201, 1
                order_id = f"ORD-{hashlib.sha1(req_id.encode()).hexdigest()[:12].upper()}"
                record = {
                    "id": order_id,
                    "intent": order_req.intent,
                    "status": "CREATED",
                    "purchase_units": body["purchase_units"],
                    "create_time": "2026-11-10T02:30:00Z",
                    "transport_mode": self.transport_mode,
                    "headers_sent": {
                        "PayPal-Request-Id": headers["PayPal-Request-Id"],
                        "User-Agent": headers["User-Agent"],
                    },
                    "links": [
                        {"href": f"{self.base_url}/v2/checkout/orders/{order_id}", "rel": "self", "method": "GET"},
                        {
                            "href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}",
                            "rel": "payer-action",
                            "method": "GET",
                        },
                        {
                            "href": f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
                            "rel": "capture",
                            "method": "POST",
                        },
                    ],
                }
            self._orders_store[order_id] = record
            self.telemetry_log.append(
                {
                    "endpoint": "POST /v2/checkout/orders",
                    "order_id": order_id,
                    "paypal_request_id": req_id,
                    "status_code": status_code,
                    "attempts": attempts,
                    "transport_mode": self.transport_mode,
                }
            )
            return record

        return self.idempotency.execute_idempotent(req_id, fingerprint, _produce)

    def authorize_order(self, order_id: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.live_http and order_id not in self._orders_store:
            raise APIMaticSchemaValidationError(f"Unknown order_id '{order_id}'")
        req_id = request_id or self.idempotency.derive_request_id("authorize-order", order_id)
        fingerprint = f"authorize:{order_id}"

        def _produce() -> Dict[str, Any]:
            if self.live_http:
                status_code, data, _, attempts = self._request_json(
                    "POST", f"/v2/checkout/orders/{order_id}/authorize", req_id, {}
                )
                auth_units = data.get("purchase_units", [{}])
                payments = auth_units[0].get("payments", {}) if auth_units else {}
                auth_list = payments.get("authorizations", [{}])
                auth_id = str(
                    data.get("authorization_id")
                    or (auth_list[0].get("id") if auth_list else "")
                    or f"AUTH-{hashlib.sha1(order_id.encode()).hexdigest()[:10].upper()}"
                )
                order = {
                    **self._orders_store.get(order_id, {}),
                    **data,
                    "id": order_id,
                    "status": data.get("status", "AUTHORIZED"),
                    "authorization_id": auth_id,
                    "transport_mode": self.transport_mode,
                }
                self._orders_store[order_id] = order
            else:
                status_code, attempts = 201, 1
                order = self._orders_store[order_id]
                auth_id = f"AUTH-{hashlib.sha1(order_id.encode()).hexdigest()[:10].upper()}"
                order["status"] = "AUTHORIZED"
                order["authorization_id"] = auth_id
            self.telemetry_log.append(
                {
                    "endpoint": f"POST /v2/checkout/orders/{order_id}/authorize",
                    "order_id": order_id,
                    "authorization_id": order["authorization_id"],
                    "paypal_request_id": req_id,
                    "status_code": status_code,
                    "attempts": attempts,
                    "transport_mode": self.transport_mode,
                }
            )
            return dict(order)

        return self.idempotency.execute_idempotent(req_id, fingerprint, _produce)

    def capture_order(self, order_id: str, request_id: Optional[str] = None) -> Dict[str, Any]:
        if not self.live_http and order_id not in self._orders_store:
            raise APIMaticSchemaValidationError(f"Unknown order_id '{order_id}'")
        req_id = request_id or self.idempotency.derive_request_id("capture-order", order_id)
        fingerprint = f"capture:{order_id}"

        def _produce() -> Dict[str, Any]:
            if self.live_http:
                status_code, data, _, attempts = self._request_json(
                    "POST", f"/v2/checkout/orders/{order_id}/capture", req_id, {}
                )
                cap_units = data.get("purchase_units", [{}])
                payments = cap_units[0].get("payments", {}) if cap_units else {}
                cap_list = payments.get("captures", [{}])
                capture_id = str(
                    data.get("capture_id")
                    or (cap_list[0].get("id") if cap_list else "")
                    or f"CAP-{hashlib.sha1((order_id + ':cap').encode()).hexdigest()[:10].upper()}"
                )
                order = {
                    **self._orders_store.get(order_id, {}),
                    **data,
                    "id": order_id,
                    "status": data.get("status", "COMPLETED"),
                    "capture_id": capture_id,
                    "transport_mode": self.transport_mode,
                }
                self._orders_store[order_id] = order
            else:
                status_code, attempts = 201, 1
                order = self._orders_store[order_id]
                capture_id = f"CAP-{hashlib.sha1((order_id + ':cap').encode()).hexdigest()[:10].upper()}"
                order["status"] = "COMPLETED"
                order["capture_id"] = capture_id
                order["capture_time"] = "2026-11-10T02:35:00Z"
            self.telemetry_log.append(
                {
                    "endpoint": f"POST /v2/checkout/orders/{order_id}/capture",
                    "order_id": order_id,
                    "capture_id": order["capture_id"],
                    "paypal_request_id": req_id,
                    "status_code": status_code,
                    "attempts": attempts,
                    "transport_mode": self.transport_mode,
                }
            )
            return dict(order)

        return self.idempotency.execute_idempotent(req_id, fingerprint, _produce)

    def create_and_send_invoice(
        self, invoice_req: InvoiceDraftRequest, request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        body = invoice_req.to_dict()
        req_id = request_id or self.idempotency.derive_request_id("create-invoice", invoice_req.invoice_number)
        fingerprint = canonical_json_fingerprint(body)

        def _produce() -> Dict[str, Any]:
            total = invoice_req.total_amount()
            if self.live_http:
                status_code, draft_data, _, attempts = self._request_json(
                    "POST", "/v2/invoicing/invoices", req_id, body
                )
                inv_id = str(draft_data.get("id") or f"INV2-{hashlib.sha1(req_id.encode()).hexdigest()[:12].upper()}")
                send_req_id = self.idempotency.derive_request_id("send-invoice", inv_id)
                self._request_json(
                    "POST",
                    f"/v2/invoicing/invoices/{inv_id}/send",
                    send_req_id,
                    {"send_to_invoicer": True, "send_to_recipient": True},
                )
                record = {
                    **draft_data,
                    "id": inv_id,
                    "status": "SENT",
                    "invoice_number": invoice_req.invoice_number,
                    "recipient_email": invoice_req.recipient_email,
                    "recipient_business_name": invoice_req.recipient_business_name,
                    "total_amount": total.to_dict(),
                    "payment_term": invoice_req.payment_term_type,
                    "transport_mode": self.transport_mode,
                }
            else:
                status_code, attempts = 201, 1
                inv_id = f"INV2-{hashlib.sha1(req_id.encode()).hexdigest()[:12].upper()}"
                record = {
                    "id": inv_id,
                    "status": "SENT",
                    "invoice_number": invoice_req.invoice_number,
                    "recipient_email": invoice_req.recipient_email,
                    "recipient_business_name": invoice_req.recipient_business_name,
                    "total_amount": total.to_dict(),
                    "payment_term": invoice_req.payment_term_type,
                    "detail": body["detail"],
                    "items": body["items"],
                    "transport_mode": self.transport_mode,
                }
            self._invoices_store[inv_id] = record
            self.telemetry_log.append(
                {
                    "endpoint": "POST /v2/invoicing/invoices",
                    "invoice_id": inv_id,
                    "paypal_request_id": req_id,
                    "status_code": status_code,
                    "attempts": attempts,
                    "transport_mode": self.transport_mode,
                }
            )
            return record

        return self.idempotency.execute_idempotent(req_id, fingerprint, _produce)

    def create_payout_batch(
        self, payout_req: PayoutBatchRequest, request_id: Optional[str] = None
    ) -> Dict[str, Any]:
        body = payout_req.to_dict()
        req_id = request_id or self.idempotency.derive_request_id("payout-batch", payout_req.sender_batch_id)
        fingerprint = canonical_json_fingerprint(body)

        def _produce() -> Dict[str, Any]:
            total_val = sum(float(i.amount.value) for i in payout_req.items)
            currency = payout_req.items[0].amount.currency_code
            if self.live_http:
                status_code, data, _, attempts = self._request_json(
                    "POST", "/v1/payments/payouts", req_id, body
                )
                header = data.get("batch_header", {})
                batch_id = str(
                    header.get("payout_batch_id")
                    or f"PAYOUT-{hashlib.sha1(req_id.encode()).hexdigest()[:10].upper()}"
                )
                record = {
                    **data,
                    "batch_header": {
                        "payout_batch_id": batch_id,
                        "batch_status": header.get("batch_status", "PENDING"),
                        "sender_batch_header": body["sender_batch_header"],
                        "amount": header.get("amount", {"currency_code": currency, "value": f"{total_val:.2f}"}),
                    },
                    "items": body["items"],
                    "transport_mode": self.transport_mode,
                }
            else:
                status_code, attempts = 201, 1
                batch_id = f"PAYOUT-{hashlib.sha1(req_id.encode()).hexdigest()[:10].upper()}"
                record = {
                    "batch_header": {
                        "payout_batch_id": batch_id,
                        "batch_status": "SUCCESS",
                        "sender_batch_header": body["sender_batch_header"],
                        "amount": {"currency_code": currency, "value": f"{total_val:.2f}"},
                    },
                    "items": body["items"],
                    "transport_mode": self.transport_mode,
                }
            self._payouts_store[batch_id] = record
            self.telemetry_log.append(
                {
                    "endpoint": "POST /v1/payments/payouts",
                    "payout_batch_id": batch_id,
                    "paypal_request_id": req_id,
                    "status_code": status_code,
                    "attempts": attempts,
                    "transport_mode": self.transport_mode,
                }
            )
            return record

        return self.idempotency.execute_idempotent(req_id, fingerprint, _produce)

    def sign_webhook_event(
        self,
        transmission_id: str,
        transmission_time: str,
        webhook_id: str,
        raw_event_body: str,
    ) -> str:
        crc = zlib.crc32(raw_event_body.encode("utf-8")) & 0xFFFFFFFF
        message = f"{transmission_id}|{transmission_time}|{webhook_id}|{crc}"
        return hmac.new(self.webhook_secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_webhook_signature(
        self,
        transmission_id: str,
        transmission_time: str,
        webhook_id: str,
        raw_event_body: str,
        transmission_sig: str,
        cert_url: Optional[str] = None,
        auth_algo: str = "SHA256withRSA",
    ) -> Dict[str, Any]:
        if not all([transmission_id, transmission_time, webhook_id, raw_event_body, transmission_sig]):
            raise APIMaticAuthError("Missing required PayPal webhook verification header or body")
        crc = zlib.crc32(raw_event_body.encode("utf-8")) & 0xFFFFFFFF
        if self.live_http and cert_url:
            req_id = self.idempotency.derive_request_id("verify-webhook", transmission_id)
            verify_payload = {
                "auth_algo": auth_algo,
                "cert_url": cert_url,
                "transmission_id": transmission_id,
                "transmission_sig": transmission_sig,
                "transmission_time": transmission_time,
                "webhook_id": webhook_id,
                "webhook_event": json.loads(raw_event_body),
            }
            _, data, _, _ = self._request_json(
                "POST", "/v1/notifications/verify-webhook-signature", req_id, verify_payload
            )
            return {
                "verification_status": data.get("verification_status", "FAILURE"),
                "transmission_id": transmission_id,
                "crc32": crc,
                "transport_mode": self.transport_mode,
            }

        expected = self.sign_webhook_event(transmission_id, transmission_time, webhook_id, raw_event_body)
        verified = hmac.compare_digest(expected, transmission_sig)
        return {
            "verification_status": "SUCCESS" if verified else "FAILURE",
            "transmission_id": transmission_id,
            "crc32": crc,
            "transport_mode": self.transport_mode,
        }
