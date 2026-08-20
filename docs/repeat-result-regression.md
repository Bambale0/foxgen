# Completed result repeat compatibility

Completed image result messages must always expose `🔁 Повторить` when a task ID is known.

Two callback formats exist in already delivered messages:

- `repeat_image_{task_id}` — current safe repeat flow;
- `repeat_result_{task_id}` — legacy completed-result keyboard.

Both callback formats are supported and open the same confirmation screen. Do not remove either handler until all historical Telegram messages can be considered expired.
