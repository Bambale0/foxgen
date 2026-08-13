import os
from uuid import uuid4

import pytest

from foxgen.admin.errors import AdminConflictError
from foxgen.admin.policy import ALL_SCOPES, AdminContext
from foxgen.admin.services import AdminServices
from foxgen.infra.database import Database


pytestmark = pytest.mark.skipif(
    os.getenv("FOXGEN_RUN_INTEGRATION") != "1",
    reason="real infrastructure tests are enabled only in the CI infrastructure job",
)


@pytest.mark.asyncio
async def test_same_admin_idempotency_key_rejects_different_balance_request() -> None:
    database = Database(os.environ["FOXGEN_DATABASE_URL"])
    services = AdminServices.build(database, bootstrap_superuser_ids=frozenset())
    context = AdminContext(
        user_id=992_001,
        role="superadmin",
        scopes=ALL_SCOPES,
        request_id=f"idempotency-{uuid4()}",
    )
    user_id = 992_101
    key = f"same-key-{uuid4()}"
    try:
        await services.users.adjust_balance(
            context=context,
            user_id=user_id,
            amount_units=100,
            reason="first request",
            idempotency_key=key,
        )
        with pytest.raises(AdminConflictError):
            await services.users.adjust_balance(
                context=context,
                user_id=user_id,
                amount_units=200,
                reason="changed request",
                idempotency_key=key,
            )
    finally:
        await database.close()
