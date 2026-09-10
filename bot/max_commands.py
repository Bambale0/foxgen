from __future__ import annotations

MAX_QUICK_COMMANDS: tuple[tuple[str, str], ...] = (
    ("start", "Текстовый бот и главное меню"),
    ("feed", "Лента работ"),
    ("prompts", "Библиотека промптов"),
    ("help", "Помощь и возможности"),
    ("ref", "Партнёрская программа"),
    ("earn", "Заработок на рефералах"),
)

MAX_QUICK_COMMAND_TARGETS = {
    "start": "max:home",
    "feed": "max:feed",
    "prompts": "max:prompts",
    "help": "max:help",
    "ref": "max:partners",
    "earn": "max:partners",
}


def max_quick_commands_payload() -> list[dict[str, str]]:
    return [
        {"name": name, "description": description}
        for name, description in MAX_QUICK_COMMANDS
    ]


def max_quick_command_name(text: str) -> str:
    token = str(text or "").strip().lower().split(maxsplit=1)[0]
    if not token.startswith("/"):
        return ""
    return token[1:].split("@", 1)[0]
