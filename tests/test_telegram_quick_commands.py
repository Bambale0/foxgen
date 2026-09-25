from pathlib import Path


EXPECTED_COMMANDS = {
    "photo": "🖼 Создать фото",
    "video": "🎬 Создать видео",
    "music": "🎵 Создать музыку",
    "motion": "🎯 Motion Control",
    "feed": "🔥 Лента работ",
    "trends": "🔥 Тренды",
    "balance": "🐾 Баланс и пополнение",
    "start": "🏠 Главное меню",
}


def test_system_menu_uses_quick_commands_instead_of_webapp():
    main = Path("bot/main.py").read_text(encoding="utf-8")
    block = main.split("async def _set_commands_chat_menu_button() -> None:", 1)[1]
    block = block.split("\nasync def ", 1)[0]

    assert 'json={"menu_button": {"type": "commands"}}' in block
    assert '"type": "web_app"' not in block


def test_registered_commands_are_action_oriented():
    main = Path("bot/main.py").read_text(encoding="utf-8")

    for command, description in EXPECTED_COMMANDS.items():
        assert (
            f'BotCommand(command="{command}", description="{description}")'
            in main
        )

    for legacy in ("prompts", "help", "ref", "earn"):
        assert f'BotCommand(command="{legacy}"' not in main


def test_quick_commands_interrupt_any_active_fsm_state():
    quick = Path("bot/handlers/quick_commands.py").read_text(encoding="utf-8")
    main = Path("bot/main.py").read_text(encoding="utf-8")

    for command in ("photo", "video", "music", "motion", "feed", "balance"):
        assert f'@router.message(Command("{command}"), StateFilter("*"))' in quick
    assert '@router.message(Command("trends", "prompts"), StateFilter("*"))' in quick
    assert '@router.message(Command("help"), StateFilter("*"))' in quick
    assert '@router.message(Command("ref", "earn"), StateFilter("*"))' in quick

    quick_include = main.index("dp.include_router(quick_commands_router)")
    generation_include = main.index("dp.include_router(generation_router)")
    common_include = main.index("dp.include_router(common_router)")
    assert quick_include < generation_include < common_include


def test_motion_quick_command_uses_clicking_user_identity():
    quick = Path("bot/handlers/quick_commands.py").read_text(encoding="utf-8")

    assert "get_user_credits(message.from_user.id)" in quick
    assert 'v_type="motion"' in quick
    assert "get_motion_control_model_keyboard" in quick


def test_deploy_reconciles_commands_menu():
    script = Path("scripts/ensure_telegram_webhook.py").read_text(encoding="utf-8")

    assert "MenuButtonCommands" in script
    assert "MenuButtonWebApp" not in script
    assert "menu_button=MenuButtonCommands()" in script
