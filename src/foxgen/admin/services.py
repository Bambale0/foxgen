from __future__ import annotations

from dataclasses import dataclass

from foxgen.admin.content_service import AdminCmsService, AdminNotificationService, AdminSupportService
from foxgen.admin.finance_service import AdminOperationService, AdminPaymentService, AdminTariffService
from foxgen.admin.operations_service import (
    AdminModerationService,
    AdminPartnerService,
    AdminPromoService,
    AdminPromptService,
    AdminRuntimeService,
)
from foxgen.admin.policy import AdminPolicy
from foxgen.admin.query_service import AdminQueryService
from foxgen.admin.repository import AdminCommandExecutor
from foxgen.admin.user_service import AdminUserService
from foxgen.infra.database import Database


@dataclass(frozen=True, slots=True)
class AdminServices:
    policy: AdminPolicy
    queries: AdminQueryService
    users: AdminUserService
    payments: AdminPaymentService
    tariffs: AdminTariffService
    operations: AdminOperationService
    support: AdminSupportService
    cms: AdminCmsService
    notifications: AdminNotificationService
    partners: AdminPartnerService
    promos: AdminPromoService
    prompts: AdminPromptService
    runtime: AdminRuntimeService
    moderation: AdminModerationService

    @classmethod
    def build(
        cls,
        database: Database,
        *,
        bootstrap_superuser_ids: frozenset[int],
    ) -> AdminServices:
        executor = AdminCommandExecutor(database)
        return cls(
            policy=AdminPolicy(database, bootstrap_superuser_ids=bootstrap_superuser_ids),
            queries=AdminQueryService(database, executor),
            users=AdminUserService(database, executor),
            payments=AdminPaymentService(database, executor),
            tariffs=AdminTariffService(database, executor),
            operations=AdminOperationService(database, executor),
            support=AdminSupportService(database, executor),
            cms=AdminCmsService(database, executor),
            notifications=AdminNotificationService(database, executor),
            partners=AdminPartnerService(database, executor),
            promos=AdminPromoService(database, executor),
            prompts=AdminPromptService(database, executor),
            runtime=AdminRuntimeService(database, executor),
            moderation=AdminModerationService(database, executor),
        )
