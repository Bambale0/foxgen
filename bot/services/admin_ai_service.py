"""Planner and helper service for the protected admin AI mode."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import aiohttp

from bot.config import config
from bot.database import normalize_promo_code

logger = logging.getLogger(__name__)

READ_ONLY_ACTIONS = {
    "stats",
    "user_info",
    "maintenance_status",
    "list_promos",
    "bot_report",
    "analyze_logs",
    "research_ai",
    "help",
    "clear_context",
}

MUTATING_ACTIONS = {
    "add_credits",
    "deduct_credits",
    "ban_user",
    "unban_user",
    "maintenance_set",
    "create_promo",
    "deactivate_promo",
}

CONFIRMATION_ACTIONS = MUTATING_ACTIONS | {"export_users"}
ALLOWED_ACTIONS = READ_ONLY_ACTIONS | MUTATING_ACTIONS | {"export_users", "unknown"}
MAX_PLAN_ACTIONS = 6
MAX_AMOUNT = 1_000_000

ACTION_ALIASES = {
    "admin_stats": "stats",
    "promo_list": "list_promos",
    "promos": "list_promos",
    "promo_create": "create_promo",
    "promo_deactivate": "deactivate_promo",
    "logs": "analyze_logs",
    "report": "bot_report",
    "research": "research_ai",
    "maintenance": "maintenance_status",
    "tech_mode": "maintenance_set",
}

SYSTEM_PROMPT = """Ты планировщик админ-действий Telegram-бота.
Верни строго один JSON без markdown.

Доступные action:
stats, user_info, add_credits, deduct_credits, ban_user, unban_user,
maintenance_status, maintenance_set, create_promo, deactivate_promo,
list_promos, export_users, bot_report, analyze_logs, research_ai,
clear_context, help, unknown.

Для сложных запросов верни actions со списком шагов.
Не придумывай ID, суммы, коды и даты.
Если данных не хватает, action=unknown.
Массовую рассылку не выполняй через ИИ.
Любые изменения данных требуют подтверждения backend-ом.
"""


def _normalize_text(value: str) -> str:
    return str(value or "").strip().lower().replace("ё", "е")


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_positive_number(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        amount = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    if amount <= 0 or amount > MAX_AMOUNT:
        return None
    return int(amount) if amount.is_integer() else round(amount, 2)


def _first_number(raw_text: str) -> int | float | None:
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)(?!\d)", raw_text)
    if not match:
        return None
    return _to_positive_number(match.group(1))


def _extract_telegram_id(raw_text: str) -> int | None:
    for match in re.finditer(r"(?<!\d)(\d{4,15})(?!\d)", raw_text):
        value = _to_int(match.group(1))
        if value:
            return value
    return None


def _extract_lines(raw_text: str, default: int = 250) -> int:
    match = re.search(r"(?<!\d)(\d{2,5})(?!\d)\s*(?:строк|lines|line)", raw_text, re.I)
    if not match:
        return default
    return max(50, min(int(match.group(1)), 1000))


def _extract_promo_code(raw_text: str) -> str | None:
    patterns = (
        r"(?:промокод|promo|код)\s*[:#-]?\s*([0-9A-Za-zА-Яа-яЁё_-]{2,32})",
        r"\b([0-9A-Za-zА-Яа-яЁё_-]{2,32})\b",
    )
    stop_words = {
        "промокод",
        "код",
        "создай",
        "создать",
        "отключи",
        "выключи",
        "деактивируй",
        "скидка",
        "лимит",
        "бананы",
    }
    for pattern in patterns:
        for match in re.finditer(pattern, raw_text, flags=re.IGNORECASE):
            value = match.group(1)
            if value.lower().replace("ё", "е") in stop_words:
                continue
            code = normalize_promo_code(value)
            if len(code) >= 2:
                return code
    return None


def _extract_named_number(raw_text: str, aliases: tuple[str, ...]) -> int | None:
    alias_pattern = "|".join(re.escape(alias) for alias in aliases)
    match = re.search(
        rf"(?:{alias_pattern})\s*[:=-]?\s*(\d{{1,8}})",
        raw_text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    value = _to_int(match.group(1))
    return value if value and value > 0 else None


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None

    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _compact_context(context: dict[str, Any] | None) -> str:
    if not context:
        return "{}"
    safe_context = {
        "admin_id": context.get("admin_id"),
        "maintenance_mode": context.get("maintenance_mode"),
        "session_memory": context.get("session_memory") or [],
    }
    text = _json_dumps(safe_context)
    return text[:5000]


def build_plan(
    action: str,
    params: dict[str, Any] | None = None,
    *,
    summary: str = "",
    confidence: float = 0.65,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return normalize_plan(
        {
            "action": action,
            "params": params or {},
            "actions": actions or [],
            "summary": summary,
            "confidence": confidence,
        }
    )


def _normalize_params(action: str, params: dict[str, Any] | None) -> dict[str, Any]:
    raw = params if isinstance(params, dict) else {}
    clean: dict[str, Any] = {}

    telegram_id = (
        raw.get("telegram_id")
        or raw.get("user_id")
        or raw.get("tg_id")
        or raw.get("target_user_id")
    )
    if telegram_id is not None:
        parsed_id = _to_int(telegram_id)
        if parsed_id:
            clean["telegram_id"] = parsed_id

    if "amount" in raw or "credits" in raw or "bananas" in raw:
        amount = _to_positive_number(
            raw.get("amount") or raw.get("credits") or raw.get("bananas")
        )
        if amount is not None:
            clean["amount"] = amount

    if "enabled" in raw or "value" in raw:
        value = raw.get("enabled", raw.get("value"))
        if isinstance(value, bool):
            clean["enabled"] = value
        elif isinstance(value, (int, float)):
            clean["enabled"] = bool(value)
        elif isinstance(value, str):
            normalized = _normalize_text(value)
            if normalized in {"1", "true", "yes", "on", "вкл", "включить", "включен"}:
                clean["enabled"] = True
            elif normalized in {"0", "false", "no", "off", "выкл", "выключить"}:
                clean["enabled"] = False

    promo_code = raw.get("code") or raw.get("promo_code")
    if promo_code is not None:
        code = normalize_promo_code(str(promo_code))
        if code:
            clean["code"] = code

    partner_name = str(raw.get("partner_name") or "").strip()
    if partner_name:
        clean["partner_name"] = partner_name[:80]

    partner_telegram_id = _to_int(raw.get("partner_telegram_id"))
    if partner_telegram_id:
        clean["partner_telegram_id"] = partner_telegram_id

    for key in ("discount_percent", "limit", "bonus_credits", "lines"):
        if key in raw:
            value = _to_int(raw.get(key))
            if value and value > 0:
                clean[key] = value

    if action == "analyze_logs":
        clean["lines"] = max(50, min(int(clean.get("lines") or 250), 1000))

    if action == "research_ai":
        query = str(raw.get("query") or raw.get("topic") or "").strip()
        if query:
            clean["query"] = query[:300]

    return clean


def normalize_plan(plan: dict[str, Any] | None) -> dict[str, Any]:
    raw = plan if isinstance(plan, dict) else {}
    action = str(raw.get("action") or "").strip().lower()
    action = ACTION_ALIASES.get(action, action)
    if action not in ALLOWED_ACTIONS:
        action = "unknown"

    raw_actions = raw.get("actions")
    actions: list[dict[str, Any]] = []
    too_many_actions = isinstance(raw_actions, list) and len(raw_actions) > MAX_PLAN_ACTIONS
    if isinstance(raw_actions, list):
        for item in raw_actions[:MAX_PLAN_ACTIONS]:
            if isinstance(item, dict):
                child = normalize_plan({**item, "actions": []})
                if child["action"] != "unknown":
                    actions.append(child)

    params = _normalize_params(action, raw.get("params"))
    summary = str(raw.get("summary") or "").strip()
    if not summary:
        summary = "План админ-действия." if action != "unknown" else "Не понял действие."

    try:
        confidence = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(confidence, 1.0))

    requires_confirmation = action in CONFIRMATION_ACTIONS or any(
        item.get("requires_confirmation") for item in actions
    )

    return {
        "action": action,
        "params": params,
        "actions": actions,
        "summary": summary[:500],
        "confidence": confidence,
        "requires_confirmation": requires_confirmation,
        "too_many_actions": too_many_actions,
    }


def validate_plan(plan: dict[str, Any], *, nested: bool = False) -> str | None:
    normalized = normalize_plan(plan)
    action = normalized["action"]
    actions = normalized.get("actions") or []

    if normalized.get("too_many_actions") or len(actions) > MAX_PLAN_ACTIONS:
        return f"Слишком длинный план: максимум {MAX_PLAN_ACTIONS} шагов."

    if actions:
        for item in actions:
            error = validate_plan(item, nested=True)
            if error:
                return error
        return None

    if action == "unknown":
        return normalized.get("summary") or "Не понял действие."
    if action not in ALLOWED_ACTIONS:
        return "Это действие не входит в allowlist ИИ-админа."

    params = normalized.get("params") or {}
    user_actions = {
        "user_info",
        "add_credits",
        "deduct_credits",
        "ban_user",
        "unban_user",
    }
    if action in user_actions and not params.get("telegram_id"):
        return "Нужен Telegram ID пользователя."

    if action in {"add_credits", "deduct_credits"} and not params.get("amount"):
        return "Нужна сумма бананов."

    if action == "maintenance_set" and "enabled" not in params:
        return "Нужно указать: включить или выключить техрежим."

    if action in {"create_promo", "deactivate_promo"} and not params.get("code"):
        return "Нужен код промокода."

    if action == "analyze_logs":
        lines = params.get("lines", 250)
        if not isinstance(lines, int) or lines < 50 or lines > 1000:
            return "Количество строк логов должно быть от 50 до 1000."

    return None


def summarize_plan_actions(plan: dict[str, Any]) -> list[str]:
    normalized = normalize_plan(plan)
    actions = normalized.get("actions") or []
    if actions:
        return [item["action"] for item in actions]
    return [normalized["action"]]


def fallback_plan_action(user_message: str) -> dict[str, Any]:
    raw = str(user_message or "").strip()
    text = _normalize_text(raw)
    telegram_id = _extract_telegram_id(raw)

    if not text:
        return build_plan("unknown", summary="Напишите задачу для ИИ-админа.")

    if any(word in text for word in ("очисти контекст", "сбрось контекст", "clear context")):
        return build_plan("clear_context", summary="Очистить контекст текущей AI-сессии.")

    if any(word in text for word in ("помощ", "инструкц", "что умеешь", "команды")):
        return build_plan("help", summary="Показать инструкцию ИИ-админа.")

    if "рассыл" in text:
        return build_plan(
            "unknown",
            summary="Массовую рассылку через ИИ не выполняю. Используйте штатный раздел админки.",
            confidence=0.9,
        )

    if "экспорт" in text and "польз" in text:
        return build_plan(
            "export_users",
            summary="Экспортировать пользователей в CSV. Требуется подтверждение.",
            confidence=0.85,
        )

    if any(word in text for word in ("отчет по боту", "отчёт по боту", "сводк по состояни", "состоянию и последним ошиб")):
        return build_plan(
            "bot_report",
            actions=[
                {"action": "stats", "params": {}, "summary": "Собрать статистику"},
                {
                    "action": "maintenance_status",
                    "params": {},
                    "summary": "Проверить техрежим",
                },
                {"action": "list_promos", "params": {}, "summary": "Показать промокоды"},
                {
                    "action": "analyze_logs",
                    "params": {"lines": _extract_lines(raw)},
                    "summary": "Проанализировать последние логи",
                },
            ],
            summary="Сделать агентный отчёт по боту.",
            confidence=0.85,
        )

    if any(word in text for word in ("лог", "ошиб", "webhook", "падал", "падали", "диагност")):
        return build_plan(
            "analyze_logs",
            {"lines": _extract_lines(raw)},
            summary="Проанализировать последние логи.",
            confidence=0.8,
        )

    if (
        any(word in text for word in ("research", "ресерч", "найди новые", "новые ии", "новые ai"))
        or ("сравни" in text and any(word in text for word in ("модел", "image", "video", "генерац")))
    ):
        return build_plan(
            "research_ai",
            {"query": raw},
            summary="Сделать research по AI-моделям и провайдерам генерации контента.",
            confidence=0.8,
        )

    if "техрежим" in text or "тех режим" in text or "maintenance" in text:
        if any(word in text for word in ("включи", "включить", "on", "enable")):
            return build_plan(
                "maintenance_set",
                {"enabled": True},
                summary="Включить техрежим. Требуется подтверждение.",
                confidence=0.85,
            )
        if any(word in text for word in ("выключи", "отключи", "выключить", "off", "disable")):
            return build_plan(
                "maintenance_set",
                {"enabled": False},
                summary="Выключить техрежим. Требуется подтверждение.",
                confidence=0.85,
            )
        return build_plan(
            "maintenance_status",
            summary="Проверить статус техрежима.",
            confidence=0.75,
        )

    if any(word in text for word in ("разбан", "разблок")):
        if not telegram_id:
            return build_plan("unknown", summary="Нужен Telegram ID пользователя для разбана.")
        return build_plan(
            "unban_user",
            {"telegram_id": telegram_id},
            summary="Разбанить пользователя. Требуется подтверждение.",
            confidence=0.85,
        )

    if any(word in text for word in ("забан", "бан ", "блокир")):
        if not telegram_id:
            return build_plan("unknown", summary="Нужен Telegram ID пользователя для бана.")
        return build_plan(
            "ban_user",
            {"telegram_id": telegram_id},
            summary="Забанить пользователя. Требуется подтверждение.",
            confidence=0.85,
        )

    if "промокод" in text or "promo" in text or "промокоды" in text:
        if any(word in text for word in ("создай", "создать", "добавь", "сделай")):
            code = _extract_promo_code(raw)
            if not code:
                return build_plan("unknown", summary="Нужен код промокода.")
            params: dict[str, Any] = {"code": code}
            discount = _extract_named_number(raw, ("скидка", "discount"))
            limit = _extract_named_number(raw, ("лимит", "limit"))
            bonus = _extract_named_number(raw, ("бананы", "бананов", "bonus"))
            if discount:
                params["discount_percent"] = discount
            if limit:
                params["limit"] = limit
            if bonus:
                params["bonus_credits"] = bonus
            return build_plan(
                "create_promo",
                params,
                summary="Создать промокод. Требуется подтверждение.",
                confidence=0.8,
            )
        if any(word in text for word in ("отключи", "выключи", "деактив")):
            code = _extract_promo_code(raw)
            if not code:
                return build_plan("unknown", summary="Нужен код промокода.")
            return build_plan(
                "deactivate_promo",
                {"code": code},
                summary="Отключить промокод. Требуется подтверждение.",
                confidence=0.8,
            )
        return build_plan("list_promos", summary="Показать промокоды.", confidence=0.75)

    if any(word in text for word in ("начисл", "добавь", "пополни")):
        amount = _first_number(raw)
        if not telegram_id:
            return build_plan("unknown", summary="Нужен Telegram ID пользователя.")
        if not amount:
            return build_plan("unknown", summary="Нужна сумма бананов.")
        return build_plan(
            "add_credits",
            {"telegram_id": telegram_id, "amount": amount},
            summary="Начислить бананы пользователю. Требуется подтверждение.",
            confidence=0.85,
        )

    if any(word in text for word in ("спиши", "списать", "вычти", "сними")):
        amount = _first_number(raw)
        if not telegram_id:
            return build_plan("unknown", summary="Нужен Telegram ID пользователя.")
        if not amount:
            return build_plan("unknown", summary="Нужна сумма бананов.")
        return build_plan(
            "deduct_credits",
            {"telegram_id": telegram_id, "amount": amount},
            summary="Списать бананы у пользователя. Требуется подтверждение.",
            confidence=0.85,
        )

    if any(word in text for word in ("пользовател", "юзер", "user", "проверь")):
        if not telegram_id:
            return build_plan("unknown", summary="Нужен Telegram ID пользователя.")
        return build_plan(
            "user_info",
            {"telegram_id": telegram_id},
            summary="Показать карточку пользователя.",
            confidence=0.8,
        )

    if any(word in text for word in ("статист", "метрик", "дашборд")):
        return build_plan("stats", summary="Показать статистику бота.", confidence=0.75)

    return build_plan(
        "unknown",
        summary="Не понял действие. Откройте инструкцию ИИ-админа или уточните задачу.",
        confidence=0.2,
    )


def redact_secrets(text: str) -> str:
    value = str(text or "")
    value = re.sub(
        r"(?i)(authorization|bearer|api[_-]?key|token|secret|password)(\s*[:=]\s*)([^\s'\"<>]+)",
        r"\1\2[redacted]",
        value,
    )
    value = re.sub(
        r"(?i)(authorization:\s*bearer\s+)[^\s]+",
        r"\1[redacted]",
        value,
    )
    return value


def fallback_log_analysis(log_text: str, metrics: dict[str, Any]) -> str:
    errors = int(metrics.get("ERROR", 0) or 0)
    warnings = int(metrics.get("WARNING", 0) or 0)
    restarts = int(metrics.get("RESTART", 0) or 0)
    webhook = int(metrics.get("WEBHOOK", 0) or 0)

    important_lines = []
    for line in str(log_text or "").splitlines():
        lowered = line.lower()
        if "error" in lowered or "warning" in lowered or "exception" in lowered:
            important_lines.append(line)
    important_lines = important_lines[-8:]

    status = "Критичных ошибок по счётчикам не видно." if errors == 0 else "Есть ошибки, стоит проверить последние ERROR/Exception."
    lines = [
        "🧪 Анализ логов",
        "",
        f"• ERROR: {errors}",
        f"• WARNING: {warnings}",
        f"• WEBHOOK: {webhook}",
        f"• RESTART: {restarts}",
        "",
        status,
    ]
    if important_lines:
        lines.append("")
        lines.append("Последние важные строки:")
        lines.extend(f"• {line[-260:]}" for line in important_lines)
    return "\n".join(lines)


class AdminAIService:
    """LLM-backed admin planner with a deterministic fallback parser."""

    ENDPOINT = "/gpt-5-2/v1/chat/completions"

    def __init__(
        self,
        *,
        kie_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 45,
    ) -> None:
        self.kie_key = config.KIE_AI_API_KEY if kie_key is None else kie_key
        self.base_url = (base_url or config.KIE_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        web_search: bool = False,
    ) -> str | None:
        if not self.kie_key:
            return None

        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "developer",
                    "content": [{"type": "text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}],
                },
            ],
            "stream": False,
            "reasoning_effort": "medium",
        }
        if web_search:
            payload["tools"] = [{"type": "function", "function": {"name": "web_search"}}]

        try:
            session = await self._get_session()
            headers = {
                "Authorization": f"Bearer {self.kie_key}",
                "Content-Type": "application/json",
            }
            async with session.post(
                f"{self.base_url}{self.ENDPOINT}",
                headers=headers,
                json=payload,
            ) as response:
                response_text = await response.text()
                if response.status != 200:
                    logger.warning(
                        "Admin AI LLM error %s: %s",
                        response.status,
                        response_text[:1000],
                    )
                    return None
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError:
                    logger.warning("Admin AI LLM returned non-JSON transport payload")
                    return None
                choices = data.get("choices") or []
                if choices:
                    content = choices[0].get("message", {}).get("content")
                    return str(content or "").strip() or None
                if isinstance(data.get("output_text"), str):
                    return data["output_text"].strip()
                return None
        except Exception:
            logger.exception("Admin AI LLM call failed")
            return None

    async def plan_action(
        self,
        user_message: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = str(user_message or "").strip()
        if not request:
            return fallback_plan_action(request)

        user_prompt = (
            f"Контекст сессии:\n{_compact_context(context)}\n\n"
            f"Задача админа:\n{request}"
        )
        response = await self._call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            web_search=False,
        )
        if response:
            parsed = _extract_json_object(response)
            if parsed:
                normalized = normalize_plan(parsed)
                if normalized["action"] != "unknown" or normalized.get("actions"):
                    return normalized
                logger.info("Admin AI LLM returned unknown plan, using it as-is")
                return normalized

        return fallback_plan_action(request)

    async def analyze_logs(self, log_text: str, metrics: dict[str, Any]) -> str:
        clean_logs = redact_secrets(log_text)[-12000:]
        fallback = fallback_log_analysis(clean_logs, metrics)
        if not clean_logs.strip():
            return fallback

        user_prompt = (
            "Метрики логов:\n"
            f"{_json_dumps(metrics)}\n\n"
            "Последние строки из allowlist-файлов:\n"
            f"{clean_logs}"
        )
        response = await self._call_llm(
            system_prompt=(
                "Проанализируй логи Telegram-бота для админа. "
                "Дай краткий отчёт: что происходит, ошибки/риски, вероятная причина, "
                "что проверить дальше. Если критичных ошибок нет, скажи это явно. "
                "Не показывай секреты и токены."
            ),
            user_prompt=user_prompt,
            web_search=False,
        )
        return response.strip() if response else fallback

    async def research_ai(self, query: str = "") -> str:
        topic = str(query or "").strip()
        prompt = (
            "Сделай актуальный research для админа Telegram-бота генерации контента. "
            "Найди новые/важные AI-модели, API и провайдеров для image/video generation. "
            "Оцени полезность для продукта, качество, стоимость/риски, что стоит протестировать. "
            "Отделяй проверенные факты от рекомендаций. "
            "Ответ должен быть кратким и практичным."
        )
        if topic:
            prompt += f"\n\nФокус запроса: {topic}"

        response = await self._call_llm(
            system_prompt=(
                "Ты research-ассистент для админа Telegram-бота. "
                "Используй web search, не меняй настройки и не предлагай автоматическое подключение API."
            ),
            user_prompt=prompt,
            web_search=True,
        )
        if response:
            return response.strip()
        return (
            "Research временно недоступен: LLM с web search не настроена или не ответила. "
            "Проверьте KIE_AI_API_KEY и повторите запрос."
        )


admin_ai_service = AdminAIService()
