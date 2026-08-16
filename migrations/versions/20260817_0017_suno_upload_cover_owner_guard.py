"""Enforce owner-bound Suno Upload & Cover input references.

Revision ID: 20260817_0017
Revises: 20260816_0016
Create Date: 2026-08-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0017"
down_revision: str | None = "20260816_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OWNER_GUARD_FUNCTION = "foxgen_validate_suno_upload_cover_input"
_OWNER_GUARD_TRIGGER = "trg_generations_suno_upload_cover_input"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_OWNER_GUARD_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            storage_key text;
            telegram_prefix text;
            miniapp_prefix text;
        BEGIN
            IF NEW.model_slug <> 'suno-v5-upload-cover' THEN
                RETURN NEW;
            END IF;

            storage_key := NEW.input_payload ->> 'input_storage_key';
            telegram_prefix := 'inputs/' || NEW.user_id::text || '/';
            miniapp_prefix := 'inputs/miniapp/' || NEW.user_id::text || '/';

            IF storage_key IS NULL
               OR btrim(storage_key) = ''
               OR storage_key LIKE '%..%'
               OR storage_key LIKE '%://%'
               OR NOT (
                   storage_key LIKE telegram_prefix || '%'
                   OR storage_key LIKE miniapp_prefix || '%'
               ) THEN
                RAISE EXCEPTION 'Suno Upload & Cover input is not owned by generation user'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_generations_suno_upload_cover_owner_input';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_OWNER_GUARD_TRIGGER}
        BEFORE INSERT OR UPDATE OF user_id, model_slug, input_payload
        ON generations
        FOR EACH ROW
        EXECUTE FUNCTION {_OWNER_GUARD_FUNCTION}();
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {_OWNER_GUARD_TRIGGER} ON generations")
    op.execute(f"DROP FUNCTION IF EXISTS {_OWNER_GUARD_FUNCTION}()")
