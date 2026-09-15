from pathlib import Path


def test_admin_router_runs_before_stateful_generation_routers() -> None:
    main_text = Path("bot/main.py").read_text(encoding="utf-8")

    admin_pos = main_text.index("dp.include_router(admin_router)")
    generation_pos = main_text.index("dp.include_router(generation_router)")
    analyzer_pos = main_text.index("dp.include_router(image_analyzer_router)")

    assert admin_pos < generation_pos
    assert admin_pos < analyzer_pos


def test_admin_command_clears_existing_fsm_before_rendering_panel() -> None:
    admin_text = Path("bot/handlers/admin.py").read_text(encoding="utf-8")
    block = admin_text.split('@router.message(Command("admin"))', 1)[1]
    block = block.split('@router.message(Command("admin_ai"))', 1)[0]

    assert "state: FSMContext" in block
    assert "await state.clear()" in block
    assert block.index("await state.clear()") < block.index("stats = await get_admin_stats()")
