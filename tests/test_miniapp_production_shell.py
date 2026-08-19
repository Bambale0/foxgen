from pathlib import Path

from foxgen.miniapp_release import MINIAPP_RELEASE

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "miniapp"
DOCKERFILE = ROOT / "Dockerfile"
DEPLOY = ROOT / ".github" / "workflows" / "deploy-production.yml"
FRONTEND_CI = ROOT / ".github" / "workflows" / "miniapp-frontend.yml"
DEPLOY_SCRIPT = ROOT / "scripts" / "deploy-production.sh"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_next_frontend_exports_under_existing_miniapp_path() -> None:
    config = read(FRONTEND / "next.config.mjs")
    layout = read(FRONTEND / "app" / "layout.tsx")

    assert "output: 'export'" in config
    assert "basePath: '/mini-app'" in config
    assert "assetPrefix: '/mini-app'" in config
    assert "trailingSlash: true" in config
    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in layout
    assert "telegram.org/js/telegram-web-app.js" in layout


def test_docker_builds_react_frontend_and_removes_legacy_static_tree() -> None:
    dockerfile = read(DOCKERFILE)

    assert "FROM node:22-bookworm-slim AS miniapp-build" in dockerfile
    assert "npm run typecheck" in dockerfile
    assert "npm test" in dockerfile
    assert "npm run build" in dockerfile
    assert "rm -rf ./src/foxgen/miniapp_static" in dockerfile
    assert (
        "COPY --from=miniapp-build /build/frontend/miniapp/out/ ./src/foxgen/miniapp_static/"
        in dockerfile
    )
    assert f'name="foxgen-miniapp-shell" content="{MINIAPP_RELEASE}"' in dockerfile
    assert "parity-app.js" not in dockerfile
    assert "backend-parity-ui.js" not in dockerfile


def test_frontend_ci_physically_clicks_navigation_before_build() -> None:
    workflow = read(FRONTEND_CI)
    navigation_test = read(FRONTEND / "__tests__" / "navigation.test.tsx")

    assert "npm run typecheck" in workflow
    assert "npm test" in workflow
    assert "npm run build" in workflow
    assert "Validate production export" in workflow
    assert "changes every primary tab by direct React state" in navigation_test
    assert "user.click(screen.getByTestId(`tab-${tab}`))" in navigation_test
    assert "opens a backend model into a real create form" in navigation_test
    assert "opens a service workspace without proxy DOM clicks" in navigation_test


def test_deploy_validates_the_same_react_export_it_ships() -> None:
    workflow = read(DEPLOY)

    assert '"frontend/miniapp/**"' in workflow
    assert "Set up Node for Mini App validation" in workflow
    assert "npm run typecheck" in workflow
    assert "npm test" in workflow
    assert "npm run build" in workflow
    assert "out/index.html" in workflow
    assert "/mini-app/_next/" in workflow
    assert "parity-app.js" in workflow  # negative smoke guard
    assert "backend-parity-ui.js" in workflow  # negative smoke guard
    assert "AUTODEPLOY_ENABLED" not in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow


def test_public_smoke_fetches_real_next_bundle_not_legacy_runtime() -> None:
    script = read(DEPLOY_SCRIPT)

    assert "miniapp_release.py" in script
    assert "src/foxgen/miniapp_static/index.html" not in script
    assert "verify_public_miniapp()" in script
    assert "foxgen-miniapp-shell" in script
    assert "/mini-app/_next/" in script
    assert "asset_path" in script
    assert "asset_url" in script
    assert '[ -s "$asset_file" ]' in script
    assert "! grep -Fq 'parity-app.js'" in script
    assert "! grep -Fq 'backend-parity-ui.js'" in script
    assert "getChatMenuButton" in script
    assert "verify_live_bot_webapp_code" in script
