"""Regression coverage for the HappyFox Telegram Bot API egress tunnel rules.

Incident (2026-09-23): the bot went silent while `/health`, the Telegram webhook
and the SSH tunnel all looked healthy. Root cause: the host INPUT chain policy is
DROP and the DNAT'ed tunnel port (18443) had no explicit ACCEPT for the container
subnet, so every outbound Bot API call timed out with TelegramNetworkError.

These tests exercise `scripts/happyfox_telegram_egress_nat.sh` against a stub
iptables so the whole rule set (including the INPUT accept) is verified without
touching a real firewall.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NAT_SCRIPT = REPO_ROOT / "scripts" / "happyfox_telegram_egress_nat.sh"
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_happyfox_dedicated.sh"
EGRESS_UNIT = REPO_ROOT / "deploy" / "systemd" / "happyfox-telegram-egress.service"
EGRESS_GUARD_UNIT = REPO_ROOT / "deploy" / "systemd" / "happyfox-telegram-egress-guard.service"
EGRESS_GUARD_TIMER = REPO_ROOT / "deploy" / "systemd" / "happyfox-telegram-egress-guard.timer"
EGRESS_CHECK = REPO_ROOT / "scripts" / "check_telegram_egress.py"

FAKE_IPTABLES_SOURCE = '''#!/usr/bin/env python3
"""Minimal iptables stub: supports -w/-t/-C/-I/-D against a JSON state file."""

import json
import os
import sys
from pathlib import Path

STATE_PATH = os.environ["FAKE_IPTABLES_STATE"]
LOG_PATH = os.environ.get("FAKE_IPTABLES_LOG", "")


def parse(argv):
    table = "filter"
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "-w":
            index += 2
        elif token == "-t":
            table = argv[index + 1]
            index += 2
        elif token in ("-C", "-I", "-D"):
            operation = token
            chain = argv[index + 1]
            index += 2
            break
        else:
            raise SystemExit(f"fake iptables: unexpected token {token}")
    else:
        raise SystemExit("fake iptables: missing operation")
    rest = argv[index:]
    if rest and rest[0].isdigit():
        rest = rest[1:]
    return table, operation, chain, " ".join(rest)


def load():
    if not Path(STATE_PATH).exists():
        return {}
    return json.loads(Path(STATE_PATH).read_text())


def save(state):
    Path(STATE_PATH).write_text(json.dumps(state, sort_keys=True))


table, operation, chain, rule = parse(sys.argv[1:])
if LOG_PATH:
    with open(LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(f"{operation} {table} {chain} {rule}\\n")

state = load()
key = f"{table}|{chain}"
rules = state.setdefault(key, [])

if operation == "-C":
    sys.exit(0 if rule in rules else 1)
if operation == "-I":
    if rule not in rules:
        rules.insert(0, rule)
    save(state)
    sys.exit(0)
if operation == "-D":
    if rule not in rules:
        sys.exit(1)
    rules.remove(rule)
    save(state)
    sys.exit(0)
raise SystemExit(f"fake iptables: unsupported operation {operation}")
'''


def _install_fake_iptables(tmp_path: Path) -> Path:
    fake = tmp_path / "fake-iptables"
    fake.write_text(FAKE_IPTABLES_SOURCE, encoding="utf-8")
    fake.chmod(0o755)
    return fake


def _run_nat(
    tmp_path: Path,
    action: str,
    *,
    seed: dict[str, list[str]] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, list[str]], str]:
    fake = _install_fake_iptables(tmp_path)
    state_path = tmp_path / "iptables-state.json"
    if seed:
        state_path.write_text(json.dumps(seed), encoding="utf-8")

    env = {
        **os.environ,
        "HAPPYFOX_TELEGRAM_EGRESS_IPTABLES": str(fake),
        "HAPPYFOX_TELEGRAM_EGRESS_SKIP_ROOT_CHECK": "1",
        "FAKE_IPTABLES_STATE": str(state_path),
        "FAKE_IPTABLES_LOG": str(tmp_path / "iptables.log"),
    }
    env.update(env_overrides or {})

    result = subprocess.run(
        ["bash", str(NAT_SCRIPT), action],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    log = (tmp_path / "iptables.log").read_text(encoding="utf-8") if (tmp_path / "iptables.log").exists() else ""
    return result, state, log


def _rules(state: dict[str, list[str]], key: str) -> list[str]:
    return state.get(key, [])


def test_egress_nat_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(NAT_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_egress_nat_up_accepts_tunnel_port_and_redirects_telegram_range(tmp_path: Path) -> None:
    result, state, _ = _run_nat(
        tmp_path,
        "up",
        env_overrides={
            "HAPPYFOX_TELEGRAM_EGRESS_CONTAINER_SUBNETS": "172.18.0.0/16 172.19.0.0/16",
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout

    input_rules = _rules(state, "filter|INPUT")
    # The DROP policy needs an explicit ACCEPT, otherwise Bot API egress dies.
    assert " ".join(["-s", "172.18.0.0/16", "-p", "tcp", "--dport", "18443", "-j", "ACCEPT"]) in input_rules
    assert " ".join(["-s", "172.19.0.0/16", "-p", "tcp", "--dport", "18443", "-j", "ACCEPT"]) in input_rules

    prerouting = _rules(state, "nat|PREROUTING")
    assert any("149.154.160.0/20" in rule and "DNAT" in rule and "172.18.0.1:18443" in rule for rule in prerouting)
    assert any("172.19.0.0/16" in rule for rule in prerouting)

    output = _rules(state, "nat|OUTPUT")
    assert any("REDIRECT" in rule and "--to-ports 18443" in rule for rule in output)


def test_egress_nat_status_fails_when_input_accept_is_missing(tmp_path: Path) -> None:
    """Incident regression: tunnel and DNAT present, INPUT accept absent."""
    seeded = {
        "nat|PREROUTING": [
            " -s 172.18.0.0/16 -p tcp -d 149.154.160.0/20 --dport 443 -j DNAT --to-destination 172.18.0.1:18443".strip()
        ],
        "nat|OUTPUT": [" -p tcp -d 149.154.160.0/20 --dport 443 -j REDIRECT --to-ports 18443".strip()],
    }

    result, _, _ = _run_nat(tmp_path, "status", seed=seeded)

    assert result.returncode == 1
    assert "outcome=missing" in result.stdout
    assert "outcome=incomplete" in result.stdout


def test_egress_nat_status_passes_after_up(tmp_path: Path) -> None:
    up_result, _, _ = _run_nat(tmp_path, "up")
    assert up_result.returncode == 0, up_result.stderr + up_result.stdout

    # The stub keeps its state in the same file, so this asserts convergence.
    status_result, _, _ = _run_nat(tmp_path, "status")

    assert status_result.returncode == 0, status_result.stdout
    assert "outcome=ok" in status_result.stdout


def test_egress_nat_up_is_idempotent(tmp_path: Path) -> None:
    first, state_first, _ = _run_nat(tmp_path, "up")
    second, state_second, _ = _run_nat(tmp_path, "up")

    assert first.returncode == 0, first.stderr + first.stdout
    assert second.returncode == 0, second.stderr + second.stdout
    assert state_second == state_first
    assert "outcome=present" in second.stdout


def test_egress_nat_down_removes_rules(tmp_path: Path) -> None:
    up_result, _, _ = _run_nat(tmp_path, "up")
    assert up_result.returncode == 0, up_result.stderr + up_result.stdout

    down_result, state, _ = _run_nat(tmp_path, "down")
    assert down_result.returncode == 0, down_result.stderr + down_result.stdout

    assert _rules(state, "filter|INPUT") == []
    assert _rules(state, "nat|PREROUTING") == []
    assert _rules(state, "nat|OUTPUT") == []

    status_result, _, _ = _run_nat(tmp_path, "status")
    assert status_result.returncode == 1


def test_egress_nat_values_are_configurable(tmp_path: Path) -> None:
    result, state, _ = _run_nat(
        tmp_path,
        "up",
        env_overrides={
            "HAPPYFOX_TELEGRAM_EGRESS_RANGE": "10.10.0.0/24",
            "HAPPYFOX_TELEGRAM_EGRESS_PORT": "29443",
            "HAPPYFOX_TELEGRAM_EGRESS_GATEWAY": "10.20.0.1",
            "HAPPYFOX_TELEGRAM_EGRESS_CONTAINER_SUBNETS": "10.20.0.0/16",
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert _rules(state, "filter|INPUT") == ["-s 10.20.0.0/16 -p tcp --dport 29443 -j ACCEPT"]
    assert _rules(state, "nat|OUTPUT") == ["-p tcp -d 10.10.0.0/24 --dport 443 -j REDIRECT --to-ports 29443"]
    assert _rules(state, "nat|PREROUTING") == [
        "-s 10.20.0.0/16 -p tcp -d 10.10.0.0/24 --dport 443 -j DNAT --to-destination 10.20.0.1:29443"
    ]


def test_egress_nat_requires_privileges_unless_seam_is_set(tmp_path: Path) -> None:
    fake = _install_fake_iptables(tmp_path)
    env = {
        **os.environ,
        "HAPPYFOX_TELEGRAM_EGRESS_IPTABLES": str(fake),
        "FAKE_IPTABLES_STATE": str(tmp_path / "state.json"),
    }
    env.pop("HAPPYFOX_TELEGRAM_EGRESS_SKIP_ROOT_CHECK", None)

    result = subprocess.run(
        ["bash", str(NAT_SCRIPT), "up"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    if os.geteuid() == 0:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode == 2
        assert "reason=root_required" in result.stdout


def test_deploy_installs_and_converges_egress_rules() -> None:
    deploy = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "install -m 0755 scripts/happyfox_telegram_egress_nat.sh /usr/local/sbin/happyfox-telegram-egress-nat" in deploy
    assert "install -m 0644 deploy/systemd/happyfox-telegram-egress.service /etc/systemd/system/happyfox-telegram-egress.service" in deploy
    assert "systemctl enable happyfox-telegram-egress.service" in deploy
    # Values come from the live Docker network, so a subnet change needs no edit.
    assert "docker network inspect foxgen_backend" in deploy
    assert "/etc/default/happyfox-telegram-egress" in deploy
    assert "systemctl restart happyfox-telegram-egress.service" in deploy
    assert "/usr/local/sbin/happyfox-telegram-egress-nat status" in deploy
    # A silent-outage revision must fail the deploy instead of looking healthy.
    assert "python -m scripts.check_telegram_egress" in deploy
    assert deploy.index("docker network inspect foxgen_backend") < deploy.index("systemctl restart happyfox-telegram-egress.service")


def test_egress_systemd_unit_applies_full_rule_set() -> None:
    unit = EGRESS_UNIT.read_text(encoding="utf-8")

    assert "ExecStartPre=/usr/local/sbin/happyfox-telegram-egress-nat up" in unit
    assert "ExecStopPost=/usr/local/sbin/happyfox-telegram-egress-nat down" in unit
    assert "EnvironmentFile=-/etc/default/happyfox-telegram-egress" in unit
    assert "${HAPPYFOX_TELEGRAM_EGRESS_PORT}" in unit
    assert "${HAPPYFOX_TELEGRAM_EGRESS_GATEWAY}" in unit
    assert "127.0.0.1:18443" not in unit
    assert "172.18.0.1:18443" not in unit
    assert "Restart=always" in unit
    assert "WantedBy=multi-user.target" in unit


def test_egress_check_uses_bounded_timeout() -> None:
    source = EGRESS_CHECK.read_text(encoding="utf-8")

    assert "AiohttpSession(timeout=EGRESS_TIMEOUT_SECONDS)" in source
    assert "get_me()" in source
    assert "telegram_egress_ok=1" in source
    assert "BOT_TOKEN" in source


def test_egress_nat_script_runs_under_systemd_without_shell() -> None:
    """The unit calls the script directly, so it must be executable and valid."""
    source = NAT_SCRIPT.read_text(encoding="utf-8")

    assert source.startswith("#!/usr/bin/env bash")
    assert "set -Eeuo pipefail" in source
    assert os.access(NAT_SCRIPT, os.X_OK), "the NAT script must be executable for the systemd unit"


def test_egress_check_compiles() -> None:
    # Compile the source in memory: writing a bytecode file into the repository
    # would fail for unprivileged CI test users and leaves no artifact behind.
    source = EGRESS_CHECK.read_text(encoding="utf-8")
    compile(source, str(EGRESS_CHECK), "exec")


def test_deploy_installs_egress_guard_timer() -> None:
    deploy = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "install -m 0644 deploy/systemd/happyfox-telegram-egress-guard.service" in deploy
    assert "install -m 0644 deploy/systemd/happyfox-telegram-egress-guard.timer" in deploy
    assert "systemctl enable --now happyfox-telegram-egress-guard.timer" in deploy
    # The rule-set status gate must run after the tunnel is restarted with the
    # live network values.
    assert deploy.index("systemctl restart happyfox-telegram-egress.service") < deploy.index(
        "/usr/local/sbin/happyfox-telegram-egress-nat status"
    )


def test_egress_guard_timer_keeps_rules_applied() -> None:
    """A firewall policy change must not silently kill Bot API egress again."""
    guard = EGRESS_GUARD_UNIT.read_text(encoding="utf-8")
    timer = EGRESS_GUARD_TIMER.read_text(encoding="utf-8")

    assert "ExecStart=/usr/local/sbin/happyfox-telegram-egress-nat up" in guard
    assert "ExecStartPost=/usr/local/sbin/happyfox-telegram-egress-nat status" in guard
    assert "Type=oneshot" in guard

    assert "Unit=happyfox-telegram-egress-guard.service" in timer
    assert "OnUnitActiveSec=5min" in timer
    assert "OnBootSec=2min" in timer
    assert "WantedBy=timers.target" in timer
