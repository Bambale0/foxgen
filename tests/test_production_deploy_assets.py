from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_autodeploy_requires_successful_main_ci_and_explicit_enablement() -> None:
    workflow = _read(".github/workflows/deploy-production.yml")

    assert "workflow_run:" in workflow
    assert "workflows:\n      - CI" in workflow
    assert "vars.AUTODEPLOY_ENABLED == 'true'" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    assert "StrictHostKeyChecking=yes" in workflow
    assert "< scripts/deploy-production.sh" in workflow


def test_remote_deploy_preserves_server_secrets_and_exact_sha() -> None:
    script = _read("scripts/deploy-production.sh")

    assert '[ -f .env ] || fail ".env is missing' in script
    assert "deployment never creates or overwrites production secrets" in script
    assert "git pull --ff-only origin main" in script
    assert 'ORIGIN_SHA="$(git rev-parse origin/main)"' in script
    assert 'DEPLOYED_SHA="$(git rev-parse HEAD)"' in script
    assert "does not match tested SHA" in script
    assert "flock -n" in script
    assert "compose run --rm migrate" in script
    assert "/health/ready" in script
    assert "cp .env" not in script
    assert "git reset --hard" not in script


def test_production_compose_keeps_stateful_services_private() -> None:
    compose = _read("docker-compose.prod.yml")

    assert "127.0.0.1:${FOXGEN_PUBLIC_API_PORT:-8080}:8080" in compose
    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose
    assert '"9000:9000"' not in compose
    assert '"9001:9001"' not in compose
    assert "FOXGEN_POSTGRES_PASSWORD is required" in compose
    assert "FOXGEN_REDIS_PASSWORD is required" in compose
    assert "no-new-privileges:true" in compose
    assert compose.count("restart: unless-stopped") >= 4


def test_production_template_contains_no_real_secrets() -> None:
    template = _read("deploy/production.env.example")

    assert "FOXGEN_ENV=production" in template
    assert "<telegram-bot-token>" in template
    assert "<kie-api-key>" in template
    assert "foxgen-development-secret" not in template
