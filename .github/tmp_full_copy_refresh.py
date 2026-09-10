from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly 1 occurrence, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replacements: dict[str, list[tuple[str, str]]] = {
    "frontend/miniapp-v0/components/tabs/studio-tab.tsx": [
        (
            "Опишите идею или добавьте референс — HappyFox поможет превратить её в фото, видео или анимацию.",
            "Напишите, что хотите получить, или загрузите референс. HappyFox проведёт к подходящей модели и настройкам — без лишних шагов.",
        ),
        (
            "Выберите, что хотите получить — дальше покажем только нужные настройки",
            "Начните с результата: фото, видео, движение или помощь. На следующем шаге останутся только нужные параметры.",
        ),
        (
            "Последние генерации, результаты и статус",
            "Здесь собраны ваши последние генерации: что готово, что ещё создаётся и где открыть результат.",
        ),
    ],
    "frontend/miniapp-v0/components/quick-action-grid.tsx": [
        (
            "Опишите идею или добавьте референс — получите готовое изображение",
            "Создайте картинку с нуля или по своему фото — лицо, стиль и детали можно сохранить.",
        ),
        (
            "Создайте ролик по тексту, фото или видео-референсу",
            "Сделайте ролик по описанию, фотографии или видео — выберите удобный способ старта.",
        ),
        (
            "Добавьте движение, мимику и камеру к готовому изображению",
            "Перенесите движение из ролика на персонажа с вашего фото.",
        ),
        (
            "Поможет с идеей, промптом и выбором подходящей модели",
            "Опишите задачу своими словами — помощник подберёт модель и соберёт сильный промпт.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/photo-tab.tsx": [
        (
            "Опишите, что хотите получить. При желании добавьте фото — оно поможет сохранить стиль, персонажа или детали.",
            "Напишите, что должно быть в кадре. Чтобы сохранить лицо, стиль, предмет или композицию, добавьте фото-референс.",
        ),
        (
            "Запустите генерацию — здесь появятся статус и готовое изображение. Результат сохранится в истории.",
            "Настройте кадр и нажмите «Создать». Здесь появятся статус и готовое изображение, а результат сохранится в истории.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/video-tab.tsx": [
        (
            "Опишите сцену и выберите подходящую модель. Если делаете видео из фото, добавьте стартовый кадр.",
            "Опишите, что происходит в кадре. Для ролика из фото добавьте стартовое изображение — остальное настраивается ниже.",
        ),
        (
            "После запуска здесь появится статус последнего видео. Готовый ролик бот пришлёт автоматически.",
            "Настройте ролик и запустите Seedance. Статус появится здесь, а готовое видео — в истории и Telegram.",
        ),
        (
            "Запустите генерацию — здесь появятся статус и готовое видео. Результат сохранится в истории.",
            "Настройте сцену и нажмите «Создать видео». Здесь появятся статус и готовый ролик, а результат сохранится в истории.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/motion-tab.tsx": [
        (
            "Загрузите фото персонажа и ролик с нужным движением — HappyFox перенесёт его на ваш образ.",
            "Дайте HappyFox два файла: кого оживить и как он должен двигаться. Движение из видео будет перенесено на персонажа с фото.",
        ),
        (
            "Фото человека или персонажа, которого хотите оживить.",
            "Исходный персонаж: лицо и образ, которые нужно сохранить в результате.",
        ),
        (
            "Ролик с движением, которое нужно повторить.",
            "Пример движения: позы, жесты и темп, которые должен повторить персонаж.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/trends-tab.tsx": [
        (
            "Готовые идеи для фото и видео — выберите тренд, добавьте свои данные и запустите генерацию.",
            "Выберите готовый пример, подставьте своё фото или данные и получите похожий результат без ручной настройки промпта.",
        ),
        (
            "Пользователи увидят пример и описание, но не увидят скрытый prompt.",
            "Пользователь увидит результат и понятное описание. Скрытый промпт и технические настройки останутся внутри шаблона.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/feed-tab.tsx": [
        (
            "Смотрите работы других пользователей, сохраняйте идеи и повторяйте понравившиеся генерации.",
            "Смотрите, что создают другие. Понравился результат — откройте работу и повторите её со своим фото или настройками.",
        ),
    ],
    "frontend/miniapp-v0/components/service-grid.tsx": [
        (
            "Загрузите фото — получите готовый промпт, который передаст стиль и детали.",
            "Загрузите пример — получите текст, который передаёт композицию, свет, стиль и важные детали.",
        ),
        (
            "Загрузите фото и аудио — персонаж заговорит и оживёт в кадре.",
            "Добавьте фото и голос — получите говорящего персонажа с синхронной мимикой.",
        ),
        (
            "Загрузите исходник и напишите, что изменить: фон, стиль, одежду или детали.",
            "Покажите исходное фото и напишите правку — фон, образ, одежду или детали можно изменить одной задачей.",
        ),
        (
            "Превратите изображение в короткое видео с нужным движением и камерой.",
            "Добавьте движение к фотографии и получите короткий ролик с нужной динамикой камеры.",
        ),
        (
            "Поможем с генерацией, оплатой или результатом.",
            "Опишите проблему — сначала поможет AI, а если нужна ручная проверка, подключится оператор.",
        ),
        (
            "Приглашайте пользователей и получайте вознаграждение.",
            "Здесь ваша ссылка, приглашённые пользователи, начисления и выплаты.",
        ),
        (
            "История, настройки и дополнительные возможности.",
            "Дополнительные инструменты и настройки HappyFox собраны в одном месте.",
        ),
        (
            "Выберите задачу — подготовим промпт, изменим фото, оживим кадр или поможем разобраться.",
            "Здесь собраны быстрые инструменты: промпт по фото, аватар, редактирование, анимация и помощь.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/services-tab.tsx": [
        (
            "Добавьте фото — соберём промпт по его стилю и деталям.",
            "Загрузите пример — HappyFox разберёт его и соберёт готовый промпт для похожего результата.",
        ),
        ("title: 'Avatar',", "title: 'Говорящий аватар',"),
        (
            "Добавьте фото персонажа и аудио для говорящего аватара.",
            "Добавьте фото и голос — дальше откроется готовый сценарий говорящего аватара.",
        ),
        (
            "Выберите фото и расскажите, что хотите изменить.",
            "Загрузите исходник и опишите правку — фон, стиль, одежду или детали.",
        ),
        (
            "Добавьте изображение и настройте движение будущего ролика.",
            "Добавьте изображение и выберите, как оно должно двигаться в готовом ролике.",
        ),
        (
            "Расскажите, с чем нужна помощь.",
            "Опишите вопрос своими словами — AI попробует решить его сразу, оператор подключится при необходимости.",
        ),
        (
            "Здесь условия программы, ссылка, статистика и выплаты.",
            "Откройте свою ссылку, статистику приглашений, начисления и выплаты.",
        ),
        (
            "Здесь история, настройки и другие возможности.",
            "Откройте дополнительные инструменты и настройки HappyFox.",
        ),
    ],
    "frontend/miniapp-v0/components/tabs/profile-tab.tsx": [
        (
            "Здесь появятся работы, опубликованные в ленте или только в профиле.",
            "Когда вы опубликуете работу, она появится здесь. Публикацию можно оставить только в профиле или показать в общей ленте.",
        ),
    ],
    "bot/handlers/common.py": [
        (
            'Создавайте фото, видео и анимацию по описанию или референсам.\\n"\n        "Выберите задачу — дальше покажу только нужные шаги. 👇',
            'Опишите результат или загрузите референс — HappyFox поможет выбрать подходящий способ генерации.\\n"\n        "Начните с нужного результата, а дальше бот покажет только необходимые шаги. 👇',
        ),
    ],
    "bot/max_product_channel.py": [
        (
            "Выберите задачу — HappyFox проведёт по нужным шагам прямо в чате.",
            "Скажите, что хотите получить, или выберите готовое действие — HappyFox проведёт по нужным шагам прямо в MAX.",
        ),
    ],
    "bot/handlers/trends_compat.py": [
        (
            "Здесь скоро появятся готовые шаблоны от команды NEUROMIX. ",
            "Здесь скоро появятся готовые шаблоны HappyFox. ",
        ),
    ],
}

for filename, pairs in replacements.items():
    for old, new in pairs:
        replace_once(filename, old, new)

cache_script = Path("scripts/ensure_happyfox_miniapp_cache_headers.py")
cache_script.write_text(
    '''from __future__ import annotations

import argparse
import re
from pathlib import Path

SERVER_RE = re.compile(r"^\\s*server\\s*\\{", re.MULTILINE)
SERVER_NAME_RE = re.compile(r"^\\s*server_name\\s+([^;]+);", re.MULTILINE)
LISTEN_443_RE = re.compile(r"^\\s*listen\\s+[^;]*\\b443\\b[^;]*;", re.MULTILINE)
MINIAPP_RE = re.compile(r"^\\s*location\\s+/mini-app/\\s*\\{", re.MULTILINE)

NO_STORE = 'add_header Cache-Control "no-cache, no-store, must-revalidate" always;'
IMMUTABLE = 'add_header Cache-Control "public, max-age=31536000, immutable" always;'


def _block_ranges(text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    lines = text.splitlines(keepends=True)
    ranges: list[tuple[int, int]] = []
    offset = 0
    start: int | None = None
    depth = 0
    for line in lines:
        code = line.split('#', 1)[0]
        if start is None and pattern.match(code):
            start = offset
            depth = code.count('{') - code.count('}')
            if depth == 0:
                ranges.append((start, offset + len(line)))
                start = None
        elif start is not None:
            depth += code.count('{') - code.count('}')
            if depth == 0:
                ranges.append((start, offset + len(line)))
                start = None
        offset += len(line)
    if start is not None:
        raise ValueError('unterminated nginx block')
    return ranges


def patch_config(text: str, domain: str = 'app.happy-fox.online') -> str:
    matches: list[tuple[int, int, str]] = []
    for start, end in _block_ranges(text, SERVER_RE):
        block = text[start:end]
        names: set[str] = set()
        for match in SERVER_NAME_RE.finditer(block):
            names.update(match.group(1).split())
        if domain in names and LISTEN_443_RE.search(block):
            matches.append((start, end, block))
    if len(matches) != 1:
        raise ValueError(f'expected one HTTPS server for {domain}, found {len(matches)}')
    start, end, server = matches[0]
    if NO_STORE in server and IMMUTABLE in server:
        return text

    mini_ranges = _block_ranges(server, MINIAPP_RE)
    if len(mini_ranges) != 1:
        raise ValueError(f'expected one /mini-app/ location, found {len(mini_ranges)}')
    loc_start, loc_end = mini_ranges[0]
    old_location = server[loc_start:loc_end]
    indent_match = re.match(r'(\\s*)location', old_location)
    indent = indent_match.group(1) if indent_match else '    '
    body_match = re.search(r'\\{(.*)\\}', old_location, re.DOTALL)
    if not body_match:
        raise ValueError('could not parse /mini-app/ body')
    directives = body_match.group(1).strip()
    if not directives:
        raise ValueError('/mini-app/ location has no directives')

    static_block = (
        f'{indent}location ^~ /mini-app/_next/static/ {{\\n'
        f'{indent}    try_files $uri =404;\\n'
        f'{indent}    {IMMUTABLE}\\n'
        f'{indent}}}\\n'
    )
    mini_block = (
        f'{indent}location /mini-app/ {{\\n'
        f'{indent}    {directives}\\n'
        f'{indent}    {NO_STORE}\\n'
        f'{indent}    add_header Pragma "no-cache" always;\\n'
        f'{indent}    add_header Expires "0" always;\\n'
        f'{indent}}}'
    )
    patched_server = server[:loc_start] + static_block + mini_block + server[loc_end:]
    patched = text[:start] + patched_server + text[end:]
    if NO_STORE not in patched_server or IMMUTABLE not in patched_server:
        raise ValueError('cache policy was not applied')
    return patched


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('config', type=Path)
    parser.add_argument('--domain', default='app.happy-fox.online')
    args = parser.parse_args()
    source = args.config.read_text(encoding='utf-8')
    patched = patch_config(source, args.domain)
    if patched != source:
        args.config.write_text(patched, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
''',
    encoding="utf-8",
)

deploy = Path("scripts/deploy_happyfox_dedicated.sh")
deploy_text = deploy.read_text(encoding="utf-8")
old = "[[ \"$(tr -d '\\\\r\\\\n' </var/www/happyfox-app/mini-app/revision.txt)\" == \"$EXPECTED_SHA\" ]]\nnginx -t\nsystemctl reload nginx\n"
new = "[[ \"$(tr -d '\\\\r\\\\n' </var/www/happyfox-app/mini-app/revision.txt)\" == \"$EXPECTED_SHA\" ]]\npython3 scripts/ensure_happyfox_miniapp_cache_headers.py /etc/nginx/sites-enabled/happyfox.conf\nnginx -t\nsystemctl reload nginx\n"
if old not in deploy_text:
    raise SystemExit("deploy cache-policy anchor not found")
deploy_text = deploy_text.replace(old, new, 1)
old_verify = "live_revision=\"$(curl -fsS --retry 8 --retry-delay 2 --retry-all-errors --max-time 20 \"$APP_ORIGIN/mini-app/revision.txt?revision=$EXPECTED_SHA\")\"\n[[ \"$live_revision\" == \"$EXPECTED_SHA\" ]]\n"
new_verify = old_verify + "curl -fsSI --retry 5 --retry-delay 2 --retry-all-errors --max-time 20 \"$APP_ORIGIN/mini-app/\" | grep -Eiq '^Cache-Control:.*no-store'\n"
if old_verify not in deploy_text:
    raise SystemExit("deploy public cache verification anchor not found")
deploy.write_text(deploy_text.replace(old_verify, new_verify, 1), encoding="utf-8")

Path("tests/test_happyfox_full_screen_copy.py").write_text(
    '''from pathlib import Path

from scripts.ensure_happyfox_miniapp_cache_headers import IMMUTABLE, NO_STORE, patch_config


def test_primary_screen_copy_is_rewritten() -> None:
    checks = {
        'frontend/miniapp-v0/components/tabs/studio-tab.tsx': 'без лишних шагов',
        'frontend/miniapp-v0/components/quick-action-grid.tsx': 'Перенесите движение из ролика',
        'frontend/miniapp-v0/components/tabs/photo-tab.tsx': 'Чтобы сохранить лицо, стиль, предмет или композицию',
        'frontend/miniapp-v0/components/tabs/video-tab.tsx': 'Для ролика из фото добавьте стартовое изображение',
        'frontend/miniapp-v0/components/tabs/motion-tab.tsx': 'кого оживить и как он должен двигаться',
        'frontend/miniapp-v0/components/tabs/trends-tab.tsx': 'без ручной настройки промпта',
        'frontend/miniapp-v0/components/tabs/feed-tab.tsx': 'повторите её со своим фото или настройками',
        'frontend/miniapp-v0/components/service-grid.tsx': 'AI, а если нужна ручная проверка',
        'frontend/miniapp-v0/components/tabs/profile-tab.tsx': 'Публикацию можно оставить только в профиле',
        'bot/handlers/common.py': 'Начните с нужного результата',
        'bot/max_product_channel.py': 'выберите готовое действие',
    }
    for filename, marker in checks.items():
        assert marker in Path(filename).read_text(encoding='utf-8'), filename


def test_stale_public_copy_does_not_return() -> None:
    source = '\\n'.join(
        Path(path).read_text(encoding='utf-8')
        for path in [
            'frontend/miniapp-v0/components/quick-action-grid.tsx',
            'frontend/miniapp-v0/components/tabs/studio-tab.tsx',
            'bot/handlers/trends_compat.py',
        ]
    )
    for stale in (
        'Картинки, арты, редактирование',
        'Динамичные сцены и анимация',
        'Motion и движение по референсу',
        'Идея, промпт и быстрый старт',
        'готовые шаблоны от команды NEUROMIX',
    ):
        assert stale not in source


def test_nginx_cache_policy_keeps_html_fresh_and_assets_immutable() -> None:
    config = '''\
server {
    server_name app.happy-fox.online;
    root /var/www/happyfox-app;
    location /mini-app/ { try_files $uri $uri/ /mini-app/index.html; }
    listen 443 ssl;
}
'''
    patched = patch_config(config)
    assert NO_STORE in patched
    assert IMMUTABLE in patched
    assert 'location ^~ /mini-app/_next/static/' in patched
    assert patch_config(patched) == patched
''',
    encoding="utf-8",
)
