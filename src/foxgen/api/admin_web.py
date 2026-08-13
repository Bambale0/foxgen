from __future__ import annotations

import html
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from foxgen.admin.errors import AdminAuthenticationError, AdminValidationError
from foxgen.admin.policy import AdminContext
from foxgen.admin.security import (
    create_admin_session_token,
    ip_is_allowed,
    require_manual_confirmation,
    verify_admin_session_token,
)
from foxgen.admin.services import AdminServices
from foxgen.api.admin import _authenticate, _services
from foxgen.core.config import Settings


class UiActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=128)
    target_id: str | None = Field(default=None, max_length=255)
    payload: dict[str, object] = Field(default_factory=dict)


def create_admin_web_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/internal/admin/ui", tags=["internal-admin-web"])

    @router.post("/session")
    async def create_session(request: Request) -> dict[str, object]:
        _ensure_web_enabled(settings)
        context = await _authenticate(request, settings)
        secret = settings.admin_hmac_key
        if secret is None:
            raise HTTPException(status_code=503, detail="Admin HMAC key is not configured")
        token = create_admin_session_token(
            secret=secret.get_secret_value(),
            admin_user_id=context.user_id,
            ttl_seconds=settings.admin_session_ttl_seconds,
        )
        return {
            "token": token,
            "expires_in": settings.admin_session_ttl_seconds,
            "url": f"/internal/admin/ui?session={token}",
        }

    @router.get("", response_class=HTMLResponse)
    async def dashboard(request: Request, session: str) -> HTMLResponse:
        _ensure_web_enabled(settings)
        context, _ = await _session_context(request, settings, session)
        return HTMLResponse(_dashboard_html(context, session))

    @router.get("/api/summary")
    async def ui_summary(
        request: Request,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
    ) -> dict[str, object]:
        context, services = await _session_context(request, settings, admin_session)
        return await services.queries.summary(context)

    @router.get("/api/{section}")
    async def ui_section(
        section: str,
        request: Request,
        q: str | None = None,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
    ) -> object:
        context, services = await _session_context(request, settings, admin_session)
        if section == "users":
            return await services.queries.users(context, query=q, limit=100, offset=0)
        if section == "payments":
            return await services.queries.payments(context, status=None, user_id=None, limit=100)
        if section == "operations":
            return await services.queries.operations(
                context,
                generation_id=None,
                status=None,
                limit=100,
            )
        if section == "tickets":
            return await services.queries.tickets(
                context,
                status=None,
                assignee_id=None,
                limit=100,
            )
        if section == "tariffs":
            return await services.queries.tariffs(context)
        if section == "campaigns":
            return await services.queries.campaigns(context, limit=100)
        if section == "moderation":
            return await services.queries.moderation(context)
        if section == "runtime":
            return await services.queries.runtime(context)
        if section == "partners":
            return {
                "summary": await services.queries.partner_summary(context),
                "withdrawals": await services.queries.partner_withdrawals(
                    context,
                    status=None,
                    limit=100,
                ),
            }
        if section == "prompts":
            return await services.queries.prompts(context, status=None, limit=100)
        if section == "cms":
            return await services.queries.cms_documents(context)
        if section == "audit":
            return await services.queries.audit(context, limit=100)
        if section == "finance":
            return await services.queries.finance(context)
        raise HTTPException(status_code=404, detail="Unknown admin UI section")

    @router.post("/api/action")
    async def ui_action(
        body: UiActionRequest,
        request: Request,
        admin_session: Annotated[str | None, Header(alias="X-Admin-Session")] = None,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Admin-Confirm")] = None,
    ) -> dict[str, object]:
        context, services = await _session_context(request, settings, admin_session)
        key = _idempotency(idempotency_key)
        destructive = {
            "user.block",
            "user.unblock",
            "user.balance_adjustment",
            "payment.reprocess",
            "operation.replay",
            "operation.refund",
            "ticket.reply",
            "tariffs.publish",
            "campaign.start",
            "campaign.cancel",
            "cms.publish",
            "model.availability",
            "runtime.flag",
            "trend.remove",
            "feed.moderate",
        }
        if body.action in destructive:
            require_manual_confirmation(confirmation)
        payload = body.payload
        target = body.target_id

        if body.action == "user.block":
            result = await services.users.block_user(
                context=context,
                user_id=_int_target(target),
                reason=_string(payload, "reason"),
                idempotency_key=key,
            )
        elif body.action == "user.unblock":
            result = await services.users.unblock_user(
                context=context,
                user_id=_int_target(target),
                idempotency_key=key,
            )
        elif body.action == "user.balance_adjustment":
            result = await services.users.adjust_balance(
                context=context,
                user_id=_int_target(target),
                amount_units=_int(payload, "amount_units"),
                reason=_string(payload, "reason"),
                idempotency_key=key,
            )
        elif body.action == "payment.recheck":
            result = await services.payments.recheck_payment(
                context=context,
                payment_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "payment.reprocess":
            result = await services.payments.reprocess_payment(
                context=context,
                payment_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "operation.replay":
            result = await services.operations.replay(
                context=context,
                operation_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "operation.refund":
            result = await services.operations.refund(
                context=context,
                operation_id=_uuid_target(target),
                reason=_string(payload, "reason"),
                idempotency_key=key,
            )
        elif body.action == "ticket.reply":
            result = await services.support.reply_ticket(
                context=context,
                ticket_id=_uuid_target(target),
                body=_string(payload, "body"),
                idempotency_key=key,
            )
        elif body.action == "tariffs.publish":
            result = await services.tariffs.publish(
                context=context,
                payload=payload,
                idempotency_key=key,
            )
        elif body.action == "campaign.create":
            segment = payload.get("segment")
            result = await services.notifications.create_campaign(
                context=context,
                name=_string(payload, "name"),
                message=_string(payload, "message"),
                segment=segment if isinstance(segment, dict) else {},
                idempotency_key=key,
            )
        elif body.action == "campaign.start":
            result = await services.notifications.start_campaign(
                context=context,
                campaign_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "campaign.cancel":
            result = await services.notifications.cancel_campaign(
                context=context,
                campaign_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "cms.save":
            metadata = payload.get("metadata")
            result = await services.cms.save_document(
                context=context,
                slug=_string(payload, "slug"),
                title=_string(payload, "title"),
                body=_string(payload, "body"),
                metadata=metadata if isinstance(metadata, dict) else {},
                idempotency_key=key,
            )
        elif body.action == "cms.publish":
            raw_version = payload.get("version_id")
            result = await services.cms.publish_document(
                context=context,
                document_id=_uuid_target(target),
                version_id=UUID(raw_version) if isinstance(raw_version, str) and raw_version else None,
                idempotency_key=key,
            )
        elif body.action == "model.availability":
            result = await services.runtime.set_model_availability(
                context=context,
                model_slug=_required_target(target),
                enabled=_bool(payload, "enabled"),
                reason=_optional_string(payload, "reason"),
                idempotency_key=key,
            )
        elif body.action == "runtime.flag":
            value = payload.get("value")
            result = await services.runtime.set_flag(
                context=context,
                key=_required_target(target),
                enabled=_bool(payload, "enabled"),
                value=value if isinstance(value, dict) else {},
                idempotency_key=key,
            )
        elif body.action == "trend.create":
            trend_payload = payload.get("payload")
            result = await services.moderation.create_trend(
                context=context,
                title=_string(payload, "title"),
                payload=trend_payload if isinstance(trend_payload, dict) else {},
                idempotency_key=key,
            )
        elif body.action == "trend.remove":
            result = await services.moderation.remove_trend(
                context=context,
                trend_id=_uuid_target(target),
                idempotency_key=key,
            )
        elif body.action == "feed.moderate":
            result = await services.moderation.moderate_feed(
                context=context,
                content_id=_required_target(target),
                action=_string(payload, "action"),
                reason=_optional_string(payload, "reason"),
                idempotency_key=key,
            )
        else:
            raise AdminValidationError("Unsupported admin web action")

        response = dict(result.payload)
        response["replayed"] = result.replayed
        return response

    return router


async def _session_context(
    request: Request,
    settings: Settings,
    token: str | None,
) -> tuple[AdminContext, AdminServices]:
    _ensure_web_enabled(settings)
    client_address = request.client.host if request.client is not None else None
    if not ip_is_allowed(client_address, settings.admin_networks):
        raise AdminAuthenticationError("Admin web request is outside the network allowlist")
    if not token:
        raise AdminAuthenticationError("Admin web session is required")
    secret = settings.admin_hmac_key
    if secret is None:
        raise HTTPException(status_code=503, detail="Admin HMAC key is not configured")
    user_id = verify_admin_session_token(secret=secret.get_secret_value(), token=token)
    request_id = request.headers.get("X-Request-Id") or str(uuid4())
    services = _services(request)
    context = await services.policy.authorize(user_id=user_id, request_id=request_id)
    return context, services


def _ensure_web_enabled(settings: Settings) -> None:
    if not settings.admin_api_enabled or not settings.admin_web_enabled:
        raise HTTPException(status_code=404, detail="Not found")


def _dashboard_html(context: AdminContext, token: str) -> str:
    safe_role = html.escape(context.role)
    safe_token = html.escape(token, quote=True)
    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FoxGen Admin</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#111827;color:#e5e7eb}}
header{{padding:16px 20px;background:#0f172a;position:sticky;top:0}}
main{{display:grid;grid-template-columns:220px 1fr;min-height:100vh}}
nav{{padding:16px;background:#0b1220}}button{{display:block;width:100%;margin:6px 0;padding:10px;border:0;border-radius:8px;cursor:pointer}}
section{{padding:20px}}pre{{white-space:pre-wrap;background:#020617;padding:16px;border-radius:12px;overflow:auto}}
.card{{background:#1f2937;padding:14px;border-radius:12px;margin-bottom:12px}}
input,textarea,select{{width:100%;box-sizing:border-box;margin:4px 0 10px;padding:8px}}
.action{{background:#374151;color:white}}.danger{{background:#7f1d1d;color:white}}
</style>
</head>
<body>
<header><b>FoxGen Admin</b> · admin {context.user_id} · role {safe_role}</header>
<main>
<nav id="nav"></nav>
<section>
<div class="card"><input id="search" placeholder="Поиск пользователя"><button class="action" onclick="loadSection('users')">Найти</button></div>
<div class="card"><b>Операторское действие</b><select id="action">
<option>user.balance_adjustment</option><option>user.block</option><option>user.unblock</option>
<option>payment.recheck</option><option>payment.reprocess</option><option>operation.replay</option><option>operation.refund</option>
<option>ticket.reply</option><option>tariffs.publish</option><option>campaign.create</option><option>campaign.start</option><option>campaign.cancel</option>
<option>cms.save</option><option>cms.publish</option><option>model.availability</option><option>runtime.flag</option>
<option>trend.create</option><option>trend.remove</option><option>feed.moderate</option>
</select><input id="target" placeholder="target_id"><textarea id="payload" rows="8" placeholder='JSON payload, например {{"amount_units":100,"reason":"manual correction"}}'></textarea><button class="danger" onclick="runAction()">Preview / confirm / execute</button></div>
<pre id="output">Loading…</pre>
</section>
</main>
<script>
const sessionToken='{safe_token}';
const sections=['summary','users','finance','payments','operations','tickets','tariffs','campaigns','partners','prompts','cms','moderation','runtime','audit'];
const nav=document.getElementById('nav');
for(const s of sections){{const b=document.createElement('button');b.textContent=s;b.onclick=()=>loadSection(s);nav.appendChild(b);}}
async function call(path,options={{}}){{options.headers=Object.assign({{}},options.headers||{{}},{{'X-Admin-Session':sessionToken,'X-Request-Id':crypto.randomUUID()}});const r=await fetch(path,options);let data;try{{data=await r.json();}}catch{{data=await r.text();}}if(!r.ok)throw new Error(JSON.stringify(data));return data;}}
async function loadSection(s){{try{{let path=s==='summary'?'/internal/admin/ui/api/summary':'/internal/admin/ui/api/'+s;if(s==='users')path+='?q='+encodeURIComponent(document.getElementById('search').value);const data=await call(path);document.getElementById('output').textContent=JSON.stringify(data,null,2);}}catch(e){{document.getElementById('output').textContent=String(e);}}}}
async function runAction(){{try{{const action=document.getElementById('action').value;const target=document.getElementById('target').value||null;let payload={{}};const raw=document.getElementById('payload').value.trim();if(raw)payload=JSON.parse(raw);const destructive=!['payment.recheck','campaign.create','cms.save','trend.create'].includes(action);if(destructive&&!confirm('Подтвердить административное действие '+action+'?'))return;const headers={{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()}};if(destructive)headers['X-Admin-Confirm']='CONFIRM';const data=await call('/internal/admin/ui/api/action',{{method:'POST',headers,body:JSON.stringify({{action,target_id:target,payload}})}});document.getElementById('output').textContent=JSON.stringify(data,null,2);}}catch(e){{document.getElementById('output').textContent=String(e);}}}}
loadSection('summary');
</script>
</body></html>"""


def _idempotency(value: str | None) -> str:
    if value is None or not value.strip():
        raise AdminValidationError("Idempotency-Key is required")
    return value.strip()


def _required_target(value: str | None) -> str:
    if value is None or not value.strip():
        raise AdminValidationError("target_id is required")
    return value.strip()


def _uuid_target(value: str | None) -> UUID:
    try:
        return UUID(_required_target(value))
    except ValueError as exc:
        raise AdminValidationError("target_id must be a UUID") from exc


def _int_target(value: str | None) -> int:
    try:
        return int(_required_target(value))
    except ValueError as exc:
        raise AdminValidationError("target_id must be an integer") from exc


def _string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AdminValidationError(f"payload.{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise AdminValidationError(f"payload.{key} must be a string")
    return value.strip() or None


def _int(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AdminValidationError(f"payload.{key} must be an integer")
    return value


def _bool(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise AdminValidationError(f"payload.{key} must be a boolean")
    return value
