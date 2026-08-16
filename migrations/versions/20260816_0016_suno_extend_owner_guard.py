"""Enforce owner-bound Suno Extend source references.

Revision ID: 20260816_0016
Revises: 20260816_0015
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0016"
down_revision: str | None = "20260816_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OWNER_GUARD_FUNCTION = "foxgen_validate_suno_extend_source"
_OWNER_GUARD_TRIGGER = "trg_generations_suno_extend_source"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_OWNER_GUARD_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            source_generation_text text;
            source_generation_uuid uuid;
            source_audio_id text;
            source_is_valid boolean;
        BEGIN
            IF NEW.model_slug <> 'suno-v5-extend' THEN
                RETURN NEW;
            END IF;

            source_generation_text := NEW.input_payload ->> 'source_generation_id';
            source_audio_id := NEW.input_payload ->> 'audio_id';

            IF source_generation_text IS NULL
               OR source_generation_text !~* '^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[1-5][0-9a-f]{{3}}-[89ab][0-9a-f]{{3}}-[0-9a-f]{{12}}$'
               OR source_audio_id IS NULL
               OR btrim(source_audio_id) = '' THEN
                RAISE EXCEPTION 'invalid Suno Extend source identity'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_generations_suno_extend_owner_source';
            END IF;

            source_generation_uuid := source_generation_text::uuid;

            SELECT EXISTS (
                SELECT 1
                FROM generations AS source_generation
                WHERE source_generation.id = source_generation_uuid
                  AND source_generation.user_id = NEW.user_id
                  AND source_generation.status = 'succeeded'
                  AND source_generation.model_slug IN ('suno-v5', 'suno-v5-extend')
                  AND EXISTS (
                      SELECT 1
                      FROM jsonb_array_elements(
                          COALESCE(source_generation.result_payload -> 'tracks', '[]'::jsonb)
                      ) AS track
                      WHERE track ->> 'id' = source_audio_id
                  )
            ) INTO source_is_valid;

            IF NOT source_is_valid THEN
                RAISE EXCEPTION 'Suno Extend source is not an owned succeeded Suno track'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_generations_suno_extend_owner_source';
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
