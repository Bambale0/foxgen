# Trend template parameters

Curated HappyFox trends may contain user-editable values while keeping the executable prompt private.

## Authoring

The administrator writes ordinary placeholders directly inside the hidden prompt:

```text
Vertical viral video. The person is {{age}} years old.
Name shown in the scene: {{name}}.
Date: {{date}}.
```

Supported placeholder keys are ASCII or Cyrillic letters followed by letters, digits or `_`. A template may expose at most eight unique fields.

Known keys receive friendly UI controls automatically:

- `{{age}}` / `{{возраст}}` → **Возраст**, number, 1–120;
- `{{name}}` / `{{имя}}` → **Имя**;
- `{{date}}` / `{{дата}}` → **Дата**;
- `{{year}}` / `{{год}}` → **Год**;
- `{{number}}` / `{{число}}` → **Число**;
- `{{city}}` / `{{город}}` → **Город**;
- `{{country}}` / `{{страна}}` → **Страна**;
- `{{profession}}` / `{{профессия}}` → **Профессия**.

Unknown valid keys become ordinary one-line text fields using the key as a label.

## Security boundary

The public trend API never returns the hidden prompt, model or provider settings. It returns only safe display metadata plus `template_fields` containing field key, label, type, placeholder and maximum length.

The browser sends only:

```json
{
  "trend_id": 17,
  "reference_urls": ["https://..."],
  "parameters": {
    "age": "28",
    "name": "Анна",
    "date": "2026-09-06"
  }
}
```

The backend reloads the approved trend, validates parameter names and values, renders placeholders into the private prompt in memory, and only then launches the generation. Client-supplied prompt, model, ratio, duration, quality or provider settings are never trusted.

Missing fields, unknown fields, multiline/control values, invalid numbers/dates and out-of-range age values are rejected before billing or provider launch.

## Backward compatibility

Trends without `{{...}}` placeholders continue to run exactly as before. Existing invalid legacy templates cannot break the public trend catalog; their field schema is omitted, while execution still fails closed until the administrator fixes the template.
