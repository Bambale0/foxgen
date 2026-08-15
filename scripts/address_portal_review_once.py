from pathlib import Path


def replace(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"missing anchor in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/foxgen/api/user_portal.py",
    "from foxgen.api.security import authenticate_submission\n",
    "from foxgen.api.security import authenticate_user_context, validate_idempotency_key\n",
)
replace(
    "src/foxgen/api/user_portal.py",
    "        return authenticate_submission(\n            settings=settings,\n            authorization=authorization,\n            user_id_header=user_id_header,\n        ).user_id",
    "        return authenticate_user_context(\n            settings=settings,\n            authorization=authorization,\n            user_id_header=user_id_header,\n        ).user_id",
)
replace(
    "src/foxgen/api/user_portal.py",
    "        user_id_header: str | None = Header(default=None, alias=\"X-FoxGen-User-Id\"),\n    ) -> dict[str, object]:\n        user_id = principal(authorization, user_id_header)\n        return _withdrawal_payload(\n            await _service(request).request_partner_withdrawal(\n                user_id=user_id,\n                amount_units=body.amount_units,\n                destination=body.destination,\n            )\n        )\n\n    return router",
    "        user_id_header: str | None = Header(default=None, alias=\"X-FoxGen-User-Id\"),\n        idempotency_key: str | None = Header(default=None, alias=\"Idempotency-Key\"),\n    ) -> dict[str, object]:\n        user_id = principal(authorization, user_id_header)\n        key = validate_idempotency_key(idempotency_key)\n        return _withdrawal_payload(\n            await _service(request).request_partner_withdrawal(\n                user_id=user_id,\n                amount_units=body.amount_units,\n                destination=body.destination,\n                idempotency_key=key,\n            )\n        )\n\n    return router",
)
replace(
    "src/foxgen/api/user_portal.py",
    "        request: Request,\n        authorization: str | None = Header(default=None),\n    ) -> dict[str, object]:\n        principal = _miniapp_principal(settings, authorization)\n        return _withdrawal_payload(\n            await _service(request).request_partner_withdrawal(\n                user_id=principal.user_id,\n                amount_units=body.amount_units,\n                destination=body.destination,\n            )\n        )\n\n    return router",
    "        request: Request,\n        authorization: str | None = Header(default=None),\n        idempotency_key: str | None = Header(default=None, alias=\"Idempotency-Key\"),\n    ) -> dict[str, object]:\n        principal = _miniapp_principal(settings, authorization)\n        key = validate_idempotency_key(idempotency_key)\n        return _withdrawal_payload(\n            await _service(request).request_partner_withdrawal(\n                user_id=principal.user_id,\n                amount_units=body.amount_units,\n                destination=body.destination,\n                idempotency_key=key,\n            )\n        )\n\n    return router",
)
replace(
    "src/foxgen/application/user_portal.py",
    "        amount_units: int,\n        destination: str,\n    ) -> PartnerWithdrawalSnapshot: ...",
    "        amount_units: int,\n        destination: str,\n        idempotency_key: str,\n    ) -> PartnerWithdrawalSnapshot: ...",
)

p = Path("src/foxgen/infra/admin_models.py")
text = p.read_text(encoding="utf-8")
text = text.replace(
    '        CheckConstraint("amount_units > 0", name="ck_partner_withdrawals_positive"),\n',
    '        UniqueConstraint("user_id", "idempotency_key", name="uq_partner_withdrawals_user_idempotency"),\n        CheckConstraint("amount_units > 0", name="ck_partner_withdrawals_positive"),\n',
    1,
)
text = text.replace(
    '    destination: Mapped[str | None] = mapped_column(String(255))\n',
    '    destination: Mapped[str | None] = mapped_column(String(255))\n    idempotency_key: Mapped[str | None] = mapped_column(String(128))\n    request_hash: Mapped[str | None] = mapped_column(String(64))\n',
    1,
)
p.write_text(text, encoding="utf-8")

p = Path("src/foxgen/infra/user_portal.py")
text = p.read_text(encoding="utf-8")
text = text.replace("from __future__ import annotations\n\n", "from __future__ import annotations\n\nimport hashlib\nimport json\n\n", 1)
old = '''    async def request_partner_withdrawal(
        self,
        *,
        user_id: int,
        amount_units: int,
        destination: str,
    ) -> PartnerWithdrawalSnapshot:
        clean_destination = destination.strip()
        if amount_units <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Сумма выплаты должна быть положительной.")
        if not 3 <= len(clean_destination) <= 255:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Укажите корректные реквизиты для выплаты.",
            )
        async with self._database.session() as session:
            async with session.begin():
                partner = await session.get(PartnerProfile, user_id, with_for_update=True)
                if partner is None:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Сначала подключите партнёрскую программу.",
                    )
                pending = await self._pending_withdrawal_units(session, user_id=user_id)
                available = max(0, partner.earned_units - partner.withdrawn_units - pending)
                if amount_units > available:
                    raise SubmissionError(
                        ErrorCode.INSUFFICIENT_CREDITS,
                        "Запрошенная выплата превышает доступный партнёрский баланс.",
                    )
                withdrawal = PartnerWithdrawal(
                    user_id=user_id,
                    amount_units=amount_units,
                    status="pending",
                    destination=clean_destination,
                )
                session.add(withdrawal)
                await session.flush()
                return self._withdrawal_snapshot(withdrawal)
'''
new = '''    async def request_partner_withdrawal(
        self,
        *,
        user_id: int,
        amount_units: int,
        destination: str,
        idempotency_key: str,
    ) -> PartnerWithdrawalSnapshot:
        clean_destination = destination.strip()
        clean_key = idempotency_key.strip()
        if amount_units <= 0:
            raise SubmissionError(ErrorCode.VALIDATION, "Сумма выплаты должна быть положительной.")
        if not 3 <= len(clean_destination) <= 255:
            raise SubmissionError(
                ErrorCode.VALIDATION,
                "Укажите корректные реквизиты для выплаты.",
            )
        if not 8 <= len(clean_key) <= 128:
            raise SubmissionError(ErrorCode.VALIDATION, "Некорректный ключ операции выплаты.")
        request_hash = hashlib.sha256(
            json.dumps(
                {"amount_units": amount_units, "destination": clean_destination},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        async with self._database.session() as session:
            async with session.begin():
                partner = await session.get(PartnerProfile, user_id, with_for_update=True)
                if partner is None:
                    raise SubmissionError(
                        ErrorCode.AUTHORIZATION,
                        "Сначала подключите партнёрскую программу.",
                    )
                existing = await session.scalar(
                    select(PartnerWithdrawal).where(
                        PartnerWithdrawal.user_id == user_id,
                        PartnerWithdrawal.idempotency_key == clean_key,
                    )
                )
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise SubmissionError(
                            ErrorCode.VALIDATION,
                            "Ключ операции уже использован с другими параметрами выплаты.",
                        )
                    return self._withdrawal_snapshot(existing)
                pending = await self._pending_withdrawal_units(session, user_id=user_id)
                available = max(0, partner.earned_units - partner.withdrawn_units - pending)
                if amount_units > available:
                    raise SubmissionError(
                        ErrorCode.INSUFFICIENT_CREDITS,
                        "Запрошенная выплата превышает доступный партнёрский баланс.",
                    )
                withdrawal = PartnerWithdrawal(
                    user_id=user_id,
                    amount_units=amount_units,
                    status="pending",
                    destination=clean_destination,
                    idempotency_key=clean_key,
                    request_hash=request_hash,
                )
                session.add(withdrawal)
                await session.flush()
                return self._withdrawal_snapshot(withdrawal)
'''
if old not in text:
    raise SystemExit("withdrawal service anchor missing")
p.write_text(text.replace(old, new, 1), encoding="utf-8")

# Frontend keeps the same key across ambiguous retries and rotates only after success.
p = Path("src/foxgen/miniapp_static/parity-app.js")
text = p.read_text(encoding="utf-8")
text = text.replace(
    "  tariff:null, supportTickets:[], supportTicket:null, partner:null, portalBusy:false,\n",
    "  tariff:null, supportTickets:[], supportTicket:null, partner:null, portalBusy:false, partnerWithdrawalKey:null,\n",
    1,
)
old = "await api('/partner/withdrawals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({amount_units,destination})});await loadPartner();render();toast('Заявка на выплату создана');"
new = "state.partnerWithdrawalKey??=`partner-withdrawal:${user().id}:${randomId()}`;await api('/partner/withdrawals',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':state.partnerWithdrawalKey},body:JSON.stringify({amount_units,destination})});state.partnerWithdrawalKey=null;await loadPartner();render();toast('Заявка на выплату создана');"
if old not in text:
    raise SystemExit("frontend withdrawal anchor missing")
p.write_text(text.replace(old, new, 1), encoding="utf-8")

# Fix integration fixture + service calls and add replay/mismatch checks.
p = Path("tests/integration/test_user_portal.py")
text = p.read_text(encoding="utf-8")
text = text.replace("                        payload={\n", "                        created_by=user_id,\n                        payload={\n", 1)
text = text.replace(
    '            destination="SBP:+79990000000",\n        )\n        assert first.status == "pending"',
    '            destination="SBP:+79990000000",\n            idempotency_key="withdrawal:first:portal-test",\n        )\n        replay = await service.request_partner_withdrawal(\n            user_id=user_id,\n            amount_units=700,\n            destination="SBP:+79990000000",\n            idempotency_key="withdrawal:first:portal-test",\n        )\n        assert replay.id == first.id\n        with pytest.raises(SubmissionError) as mismatch:\n            await service.request_partner_withdrawal(\n                user_id=user_id,\n                amount_units=600,\n                destination="SBP:+79990000000",\n                idempotency_key="withdrawal:first:portal-test",\n            )\n        assert mismatch.value.code == ErrorCode.VALIDATION\n        assert first.status == "pending"',
    1,
)
text = text.replace(
    '                destination="SBP:+79990000000",\n            )\n        assert overspend.value.code',
    '                destination="SBP:+79990000000",\n                idempotency_key="withdrawal:overspend:portal-test",\n            )\n        assert overspend.value.code',
    1,
)
p.write_text(text, encoding="utf-8")

# Update unit/API fake signatures broadly.
for path in (Path("tests/test_user_portal_api.py"),):
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "async def request_partner_withdrawal(self, *, user_id: int, amount_units: int, destination: str):",
        "async def request_partner_withdrawal(self, *, user_id: int, amount_units: int, destination: str, idempotency_key: str):",
    )
    path.write_text(text, encoding="utf-8")

migration = Path("migrations/versions/20260816_0011_partner_withdrawal_idempotency.py")
migration.write_text('''"""add durable idempotency to partner withdrawals\n\nRevision ID: 20260816_0011\nRevises: 20260815_0010\n"""\n\nfrom alembic import op\nimport sqlalchemy as sa\n\nrevision = "20260816_0011"\ndown_revision = "20260815_0010"\nbranch_labels = None\ndepends_on = None\n\n\ndef upgrade() -> None:\n    op.add_column("partner_withdrawals", sa.Column("idempotency_key", sa.String(length=128), nullable=True))\n    op.add_column("partner_withdrawals", sa.Column("request_hash", sa.String(length=64), nullable=True))\n    op.create_unique_constraint(\n        "uq_partner_withdrawals_user_idempotency",\n        "partner_withdrawals",\n        ["user_id", "idempotency_key"],\n    )\n\n\ndef downgrade() -> None:\n    op.drop_constraint("uq_partner_withdrawals_user_idempotency", "partner_withdrawals", type_="unique")\n    op.drop_column("partner_withdrawals", "request_hash")\n    op.drop_column("partner_withdrawals", "idempotency_key")\n''', encoding="utf-8")

# API docs: remove stale future-language and append exact safe routes.
for doc_path in ("docs/miniapp.md", "docs/api-reference.md"):
    p = Path(doc_path)
    text = p.read_text(encoding="utf-8")
    text = text.replace("partners, user support and published tariffs", "payments and referral attribution")
    text = text.replace("partner/support/tariff", "payment/referral")
    marker = "<!-- happy-fox-user-portal-routes -->"
    if marker not in text:
        text += '''\n\n<!-- happy-fox-user-portal-routes -->\n## Happy Fox user portal routes\n\nOwner-scoped Mini App routes authenticated by the Telegram-derived JWT:\n\n- `GET /v1/miniapp/tariff` — current published tariff version;\n- `GET|POST /v1/miniapp/support` — list/create support tickets;\n- `GET /v1/miniapp/support/{ticket_id}` — ticket detail/history;\n- `POST /v1/miniapp/support/{ticket_id}/messages` — reply;\n- `POST /v1/miniapp/support/{ticket_id}/close` — close own ticket;\n- `GET /v1/miniapp/partner` — partner dashboard and withdrawals;\n- `POST /v1/miniapp/partner/join` — idempotent partner enrollment;\n- `POST /v1/miniapp/partner/withdrawals` — create a withdrawal request and requires `Idempotency-Key`.\n\nThe equivalent `/v1/user-portal/*` trusted-service routes authenticate user context independently of the paid-task submission kill switch. Admin review/approval actions remain under the privileged admin control plane.\n'''
    p.write_text(text, encoding="utf-8")
