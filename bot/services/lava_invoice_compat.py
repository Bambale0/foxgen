from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from types import ModuleType
from typing import Any

from bot.services import lava_payment_safety as safety
from bot.services.lava_service import LavaService, lava_service

logger = logging.getLogger(__name__)

_INSTALL_MARKER = "_lava_invoice_compat_installed"
_TRANSACTION_MARKER = "_lava_invoice_transaction_normalizer"


async def _create_invoice_compatible(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Create a Lava invoice without requiring contractId in the create response.

    The current POST /api/v3/invoice response can contain only the invoice ``id``
    and ``paymentUrl``. ``contractId`` is a contract/webhook identifier and may
    become available later. The invoice ID is sufficient to persist the local
    transaction and query GET /api/v2/invoices/{id}.
    """

    # Call the class implementation directly. The previous safety layer replaces
    # the instance method and incorrectly rejects successful invoice-only replies.
    response = await LavaService.create_invoice(lava_service, *args, **kwargs)
    if not isinstance(response, dict) or not response.get("ok"):
        return response

    invoice_id = lava_service.extract_invoice_id(response)
    if not invoice_id:
        logger.error("Rejected Lava invoice response without invoice id")
        return {
            **response,
            "ok": False,
            "error": "Lava did not return invoiceId",
        }

    contract_id = lava_service.extract_contract_id(response)
    if contract_id:
        try:
            await safety._save_binding(contract_id, invoice_id)
        except Exception:
            # Do not invalidate a successfully created invoice. The webhook and
            # reconcile paths can rebuild this mapping from the invoice API.
            logger.exception(
                "Could not persist Lava contract/invoice mapping at creation"
            )
    else:
        logger.info(
            "Accepted Lava invoice response with invoice_id=%s and no contractId; "
            "binding will be resolved from the invoice API/webhook",
            invoice_id,
        )

    return response


def _make_transaction_normalizer(
    original: Callable[..., Awaitable[Any]],
) -> Callable[..., Awaitable[Any]]:
    signature = inspect.signature(original)

    async def create_transaction_with_invoice_id(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind_partial(*args, **kwargs)
        provider = str(bound.arguments.get("provider") or "").lower()
        payment_id = str(bound.arguments.get("payment_id") or "").strip()

        if provider == "lava" and payment_id:
            mapped_invoice_id = await safety._invoice_id_for_contract(payment_id)
            if mapped_invoice_id:
                bound.arguments["payment_id"] = mapped_invoice_id

        return await original(*bound.args, **bound.kwargs)

    setattr(create_transaction_with_invoice_id, _TRANSACTION_MARKER, True)
    return create_transaction_with_invoice_id


def _install_transaction_normalizer(module: ModuleType) -> None:
    original = getattr(module, "create_transaction", None)
    if not callable(original) or getattr(original, _TRANSACTION_MARKER, False):
        return
    module.create_transaction = _make_transaction_normalizer(original)


def _make_lookup_with_discovery(
    original_lookup: Callable[..., Awaitable[Any | None]],
) -> Callable[..., Awaitable[Any | None]]:
    async def lookup_lava_transaction(
        *,
        contract_id: str,
        order_id: str | None,
    ) -> Any | None:
        transaction = await original_lookup(
            contract_id=contract_id,
            order_id=order_id,
        )
        if transaction:
            return transaction

        # New invoice creation responses may not expose contractId. Resolve the
        # relation when the first webhook arrives, then retry the local lookup by
        # the invoice ID stored in transactions.payment_id.
        invoice_id = await safety._discover_invoice_id_by_contract(contract_id)
        if not invoice_id:
            return None

        return await original_lookup(
            contract_id=contract_id,
            order_id=order_id,
        )

    return lookup_lava_transaction


async def _provider_status_compatible(
    transaction: Any,
    *,
    contract_id: str | None = None,
    retry_delays: Iterable[float] = (0.0, 0.75, 1.5),
) -> tuple[str, str | None]:
    """Query by invoice ID first and bind a later webhook contractId.

    New rows store the invoice ID. Legacy rows may still store contractId, so the
    already-installed get_invoice compatibility wrapper remains the fallback.
    """

    payment_id = str(getattr(transaction, "payment_id", "") or "").strip()
    contract = str(contract_id or "").strip()

    candidates: list[str] = []
    for candidate in (payment_id, contract):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return "", None

    last_status = ""
    resolved_invoice_id: str | None = None

    for delay in retry_delays:
        if delay:
            await asyncio.sleep(delay)

        invoice: dict[str, Any] | None = None
        for candidate in candidates:
            invoice = await lava_service.get_invoice(candidate)
            if invoice:
                break
        if not invoice:
            continue

        extracted_invoice_id = lava_service.extract_invoice_id(invoice)
        if extracted_invoice_id:
            resolved_invoice_id = str(extracted_invoice_id)
        elif candidate == payment_id:
            # Current transactions persist the invoice ID directly. Some
            # status endpoints omit it from the response body, so keep the
            # identifier that successfully resolved the invoice.
            resolved_invoice_id = payment_id

        if contract and resolved_invoice_id and contract != resolved_invoice_id:
            try:
                await safety._save_binding(contract, resolved_invoice_id)
            except Exception:
                logger.exception(
                    "Could not persist Lava contract/invoice mapping during status check"
                )

        last_status = (
            lava_service.webhook_status(invoice)
            or str(invoice.get("status") or "").lower()
        )
        if last_status not in safety._PENDING_STATUSES:
            break

    if not resolved_invoice_id and contract:
        resolved_invoice_id = await safety._invoice_id_for_contract(contract)

    return last_status, resolved_invoice_id


def install_lava_invoice_compat(
    payments_module: ModuleType,
    lava_checkout_module: ModuleType,
) -> None:
    """Install the invoice-only response compatibility fix once."""

    if getattr(lava_service, _INSTALL_MARKER, False):
        return

    original_lookup = safety._lookup_lava_transaction

    # Replace only the incorrect creation wrapper. The existing safe get_invoice,
    # webhook, authentication and atomic completion layers stay active.
    lava_service.create_invoice = _create_invoice_compatible  # type: ignore[method-assign]
    safety._lookup_lava_transaction = _make_lookup_with_discovery(original_lookup)
    safety._provider_status = _provider_status_compatible

    _install_transaction_normalizer(payments_module)
    _install_transaction_normalizer(lava_checkout_module)

    setattr(lava_service, _INSTALL_MARKER, True)
    logger.info("Installed Lava invoice-only response compatibility layer")
