"""Enterprise MCP tool contracts per system of record, wrapping injected backends.

Each ``build_*_server(backend)`` registers the contract tools the backend implements (a
backend method with the same name as the tool). Projects pass their mock systems of record
(or a thin adapter); production would pass an SAP / Dynamics / ServiceNow client. The tool
surface is deliberately small and business-shaped (``get_purchase_order``,
``submit_purchase_order``) - never ``run_any_bapi``.

Write tools default to ``dry_run=True`` (preview, no side effect) and require an
``idempotency_key``; replays return the original result (see ``kit.SorServer``).
"""

# No `from __future__ import annotations`: FastMCP builds JSON schemas from real annotations.
from typing import Any

from shared.mcp_servers.kit import SorServer

Json = dict[str, Any]


def _preview(tool: str, **args: Any) -> Json:
    return {"dry_run": True, "tool": tool, "would_apply": args}


def _has(backend: Any, name: str) -> bool:
    return callable(getattr(backend, name, None))


# --------------------------------------------------------------------------- OMS
def build_oms_server(backend: Any) -> SorServer:
    srv = SorServer("oms", "Order management system (orders, shipments).", "OMS")
    if _has(backend, "get_order"):

        @srv.read
        def get_order(order_id: str) -> Json:
            """Order header, lines, delivery date and refund status by order id."""
            return backend.get_order(order_id)

    if _has(backend, "mark_order_refunded"):

        @srv.write
        def mark_order_refunded(
            order_id: str, refund_id: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Flag an order as refunded with the payment refund id."""
            if dry_run:
                return _preview("mark_order_refunded", order_id=order_id, refund_id=refund_id)
            return backend.mark_order_refunded(order_id, refund_id)

    return srv


# --------------------------------------------------------------------------- CRM
def build_crm_server(backend: Any) -> SorServer:
    srv = SorServer("crm", "CRM: customers, accounts, interactions, deals, cases.", "CRM")
    if _has(backend, "verify_customer"):

        @srv.read
        def verify_customer(customer_id: str, email: str) -> Json:
            """Check that the email on file matches the customer id."""
            return {
                "customer_id": customer_id,
                "verified": backend.verify_customer(customer_id, email),
            }

    if _has(backend, "get_interaction_history"):

        @srv.read
        def get_interaction_history(account: str) -> list[Json]:
            """Recent meetings, calls and emails with an account."""
            return backend.get_interaction_history(account)

    if _has(backend, "get_open_deals"):

        @srv.read
        def get_open_deals(account: str) -> list[Json]:
            """Open opportunities for an account (stage, amount, close date)."""
            return backend.get_open_deals(account)

    if _has(backend, "get_account"):

        @srv.read
        def get_account(account_id: str) -> Json:
            """Receivables account: balance, days past due, flags, contact preferences."""
            return backend.get_account(account_id)

    if _has(backend, "get_contact_history"):

        @srv.read
        def get_contact_history(account_id: str) -> list[Json]:
            """Outbound/inbound contact attempts for an account."""
            return backend.get_contact_history(account_id)

    if _has(backend, "add_case_note"):

        @srv.write
        def add_case_note(
            customer_id: str, note: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Append a note to the customer's case timeline."""
            if dry_run:
                return _preview("add_case_note", customer_id=customer_id)
            return backend.add_case_note(customer_id, note) or {"ok": True}

    if _has(backend, "send_customer_message"):

        @srv.write
        def send_customer_message(
            account_id: str, channel: str, body: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Send a message to the customer on an approved channel."""
            if dry_run:
                return _preview("send_customer_message", account_id=account_id, channel=channel)
            return backend.send_customer_message(account_id, channel, body)

    return srv


# --------------------------------------------------------------------------- Ticketing
def build_ticketing_server(backend: Any) -> SorServer:
    srv = SorServer("ticketing", "Service desk tickets (ServiceNow/Zendesk-like).", "Ticketing")
    if _has(backend, "list_tickets"):

        @srv.read
        def list_tickets(account: str) -> list[Json]:
            """Open and recent support tickets for an account."""
            return backend.list_tickets(account)

    if _has(backend, "get_ticket"):

        @srv.read
        def get_ticket(ticket_id: str) -> Json:
            """A ticket by id."""
            return backend.get_ticket(ticket_id)

    if _has(backend, "create_ticket"):

        @srv.write
        def create_ticket(
            queue: str,
            subject: str,
            summary: str,
            priority: str,
            idempotency_key: str,
            dry_run: bool = True,
        ) -> Json:
            """Create (route) a ticket into a queue."""
            if dry_run:
                return _preview("create_ticket", queue=queue, priority=priority)
            return backend.create_ticket(queue, subject, summary, priority, idempotency_key)

    return srv


# --------------------------------------------------------------------------- ERP (SAP-like)
def build_erp_server(backend: Any) -> SorServer:
    srv = SorServer("erp", "ERP: purchasing, receiving, AP, inventory, suppliers.", "ERP")
    if _has(backend, "get_purchase_order"):

        @srv.read
        def get_purchase_order(po_number: str) -> Json:
            """PO header and lines (qty, unit price) by PO number."""
            return backend.get_purchase_order(po_number)

    if _has(backend, "get_goods_receipts"):

        @srv.read
        def get_goods_receipts(po_number: str) -> dict[str, float]:
            """Received quantity per PO line."""
            return backend.get_goods_receipts(po_number)

    if _has(backend, "get_invoiced_quantities"):

        @srv.read
        def get_invoiced_quantities(po_number: str) -> dict[str, float]:
            """Quantity already invoiced per PO line."""
            return backend.get_invoiced_quantities(po_number)

    if _has(backend, "is_invoice_posted"):

        @srv.read
        def is_invoice_posted(invoice_number: str) -> Json:
            """Whether a vendor invoice number has already been posted."""
            return {
                "invoice_number": invoice_number,
                "posted": backend.is_invoice_posted(invoice_number),
            }

    if _has(backend, "post_invoice"):

        @srv.write
        def post_invoice(invoice: Json, idempotency_key: str, dry_run: bool = True) -> Json:
            """Post a matched vendor invoice to AP."""
            if dry_run:
                return _preview("post_invoice", invoice_number=invoice.get("invoice_number"))
            return {"document_id": backend.post_invoice(invoice)}

    if _has(backend, "get_stock"):

        @srv.read
        def get_stock(sku: str) -> Json:
            """On-hand, safety stock and lead time for a SKU (inventory gold)."""
            return backend.get_stock(sku)

    if _has(backend, "get_open_purchase_orders"):

        @srv.read
        def get_open_purchase_orders(sku: str) -> list[Json]:
            """Open inbound POs for a SKU."""
            return backend.get_open_purchase_orders(sku)

    if _has(backend, "list_suppliers"):

        @srv.read
        def list_suppliers(sku: str) -> list[Json]:
            """Approved suppliers for a SKU."""
            return backend.list_suppliers(sku)

    if _has(backend, "get_supplier_quote"):

        @srv.read
        def get_supplier_quote(supplier: str, sku: str, qty: int) -> Json:
            """Price and lead-time quote from a supplier."""
            return backend.get_supplier_quote(supplier, sku, qty)

    if _has(backend, "create_po_draft"):

        @srv.write
        def create_po_draft(po: Json, idempotency_key: str, dry_run: bool = True) -> Json:
            """Create a draft purchase order (not yet sent to the supplier)."""
            if dry_run:
                return _preview("create_po_draft", po=po)
            return backend.create_po_draft(po)

    if _has(backend, "submit_purchase_order"):

        @srv.write(dedupe=False)  # backend dedupes on the key itself
        def submit_purchase_order(
            draft_id: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Release an approved draft PO to the supplier."""
            if dry_run:
                return _preview("submit_purchase_order", draft_id=draft_id)
            return backend.submit_purchase_order(draft_id, idempotency_key)

    if _has(backend, "cancel_po_draft"):

        @srv.write
        def cancel_po_draft(
            draft_id: str, reason: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Cancel a draft PO (compensation); refused once the PO has been released."""
            if dry_run:
                return _preview("cancel_po_draft", draft_id=draft_id, reason=reason)
            return backend.cancel_po_draft(draft_id, reason)

    return srv


# --------------------------------------------------------------------------- Supplier portal
def build_suppliers_server(backend: Any) -> SorServer:
    srv = SorServer(
        "suppliers", "Supplier portal / quote network (external, untrusted text).", "Suppliers"
    )
    if _has(backend, "list_suppliers"):

        @srv.read
        def list_suppliers(sku: str) -> list[Json]:
            """Approved suppliers for a SKU (with preferred flag)."""
            return backend.list_suppliers(sku)

    if _has(backend, "get_supplier_quote"):

        @srv.read
        def get_supplier_quote(supplier: str, sku: str, qty: int) -> Json:
            """Price, MOQ and lead-time quote from one supplier."""
            return backend.get_supplier_quote(supplier, sku, qty)

    return srv


# --------------------------------------------------------------------------- Payments
def build_payments_server(backend: Any) -> SorServer:
    srv = SorServer("payments", "Payments and receivables ledger.", "Payments")
    if _has(backend, "issue_refund"):

        @srv.write(dedupe=False)  # backend dedupes on the key itself
        def issue_refund(
            order_id: str, amount: float, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Refund an amount to the original payment method."""
            if dry_run:
                return _preview("issue_refund", order_id=order_id, amount=amount)
            return backend.issue_refund(order_id, amount, idempotency_key)

    if _has(backend, "quote_payment_plan"):

        @srv.read
        def quote_payment_plan(account_id: str, months: int, discount_pct: float) -> Json:
            """Compute installments for a proposed plan (no side effects)."""
            return backend.quote_payment_plan(account_id, months, discount_pct)

    if _has(backend, "create_payment_plan"):

        @srv.write(dedupe=False)  # backend dedupes on the key itself
        def create_payment_plan(
            account_id: str,
            plan: Json,
            approved_by: str,
            idempotency_key: str,
            dry_run: bool = True,
        ) -> Json:
            """Book an approved payment plan on the receivables ledger."""
            if dry_run:
                return _preview("create_payment_plan", account_id=account_id, plan=plan)
            return backend.create_payment_plan(account_id, plan, approved_by, idempotency_key)

    return srv


# --------------------------------------------------------------------------- Ops / SRE
def build_ops_server(backend: Any) -> SorServer:
    srv = SorServer("ops", "Observability + deployment system (logs, metrics, deploys).", "Ops")
    if _has(backend, "query_logs"):

        @srv.read
        def query_logs(service: str, pattern: str = "ERROR", minutes: int = 60) -> Json:
            """Matching log lines for a service in the last N minutes."""
            return backend.query_logs(service, pattern, minutes)

    if _has(backend, "get_metrics"):

        @srv.read
        def get_metrics(service: str, metric: str, minutes: int = 60) -> Json:
            """A metric time series summary for a service."""
            return backend.get_metrics(service, metric, minutes)

    if _has(backend, "recent_deploys"):

        @srv.read
        def recent_deploys(service: str, hours: int = 24) -> Json:
            """Deploys of a service in the last N hours."""
            return backend.recent_deploys(service, hours)

    if _has(backend, "rollback_deploy"):

        @srv.write
        def rollback_deploy(
            service: str, to_version: str, idempotency_key: str, dry_run: bool = True
        ) -> Json:
            """Roll a service back to a previous version."""
            if dry_run:
                return _preview("rollback_deploy", service=service, to_version=to_version)
            return backend.rollback_deploy(service, to_version, idempotency_key)

    return srv


# --------------------------------------------------------------------------- Semantic model
def build_analytics_server(backend: Any) -> SorServer:
    srv = SorServer(
        "analytics", "Certified semantic model (measures over gold tables).", "Semantic model"
    )
    if _has(backend, "get_measure"):

        @srv.read
        def get_measure(measure: str, entity: str, grain: str = "week") -> Json:
            """A certified measure for an entity at a grain - not free-form SQL."""
            return backend.get_measure(measure, entity, grain)

    return srv


BUILDERS = {
    "oms": build_oms_server,
    "crm": build_crm_server,
    "ticketing": build_ticketing_server,
    "erp": build_erp_server,
    "payments": build_payments_server,
    "ops": build_ops_server,
    "analytics": build_analytics_server,
    "suppliers": build_suppliers_server,
}
