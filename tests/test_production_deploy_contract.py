from pathlib import Path


def _deploy_script() -> str:
    return (Path(__file__).resolve().parents[1] / "scripts" / "deploy-production.sh").read_text(
        encoding="utf-8"
    )


def test_deploy_force_recreates_app_services_from_tested_sha() -> None:
    script = _deploy_script()

    assert 'EXPECTED_IMAGE="foxgen:$DEPLOYED_SHA"' in script
    assert "compose up -d --force-recreate --no-deps api worker bot" in script
    assert 'assert_service_image "$service"' in script
    assert "docker inspect --format '{{.Config.Image}}'" in script


def test_deploy_reloads_local_https_ingress_after_api_recreation() -> None:
    script = _deploy_script()

    assert "reload_local_https_ingress" in script
    assert '--filter "network=$backend_network" --filter publish=443' in script
    assert "nginx -t" in script
    assert "nginx -s reload" in script


def test_deploy_smokes_exact_happy_fox_release_and_telegram_menu() -> None:
    script = _deploy_script()

    assert "resolved_miniapp_url" in script
    assert "verify_public_miniapp" in script
    assert "cache_control" in script
    assert '[[ "${cache_control,,}" == *"no-store"* ]]' in script
    assert 'name=\\"foxgen-miniapp-shell\\" content=\\"${expected_release}\\"' in script
    assert "/mini-app/_next/" in script
    assert "asset_path" in script
    assert "asset_url" in script
    assert "getChatMenuButton" in script
    assert 'result.get("type") != "web_app"' in script
    assert 'result.get("text") != "Happy Fox"' in script
    assert "if actual != expected:" in script


def test_streamed_deploy_disables_stdin_for_one_shot_compose_runs() -> None:
    script = _deploy_script()

    assert "compose run -T --rm minio-init </dev/null" in script
    assert "compose run -T --rm migrate </dev/null" in script
    assert "compose run --rm minio-init" not in script
    assert "compose run --rm migrate" not in script


def test_deploy_never_reconciles_untracked_production_files() -> None:
    script = _deploy_script()

    assert "git diff --name-only -z" in script
    assert "git diff --cached --name-only -z" in script
    assert "git status --porcelain" not in script
    assert "git clean" not in script
