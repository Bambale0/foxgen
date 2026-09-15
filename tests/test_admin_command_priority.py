from pathlib import Path


def test_admin_router_runs_before_stateful_generation_routers() -> None:
    main_text = Path("bot/main.py").read_text(encoding="utf-8")

    admin_pos = main_text.index("dp.include_router(admin_router)")
    generation_pos = main_text.index("dp.include_router(generation_router)")
    analyzer_pos = main_text.index("dp.include_router(image_analyzer_router)")

    assert admin_pos < generation_pos
    assert admin_pos < analyzer_pos
