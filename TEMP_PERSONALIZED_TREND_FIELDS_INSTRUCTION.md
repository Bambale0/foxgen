# Temporary implementation instruction — personalized trend fields

Implement personalized variables for reusable trend/templates without exposing the hidden prompt.

Required behavior:
- Admin can define up to 6 user fields per trend/template.
- Supported field types: `text` and `number`.
- Field metadata lives inside the existing structured trend/template settings where possible; avoid a new DB table unless this repository genuinely requires one.
- Hidden prompt may contain placeholders like `{{Возраст}}`, `{{Имя}}`, `{{Год}}`, `{{Надпись}}`.
- User repeat/run UI renders only the declared fields and sends only user-entered values plus existing references/inputs.
- Backend must load the trusted saved template, validate submitted values against the saved field schema, reject unknown fields, render placeholders server-side, and never expose the source hidden prompt to the client.
- Number fields support min/max validation. Text fields support max length. Required defaults to true.
- Existing trends/templates without `user_fields` must behave exactly as before.
- Keep existing model/quality/settings trust boundary: client cannot override protected generation settings.
- Add regression tests covering server-side substitution, invalid/missing/unknown values, privacy/redaction, old-template compatibility, and frontend payload/UI behavior.
- Use repository instructions/AGENTS and mandatory repo skills before implementation.

Example birthday template:
- user field: `{ key: "Возраст", label: "Возраст", type: "number", min: 1, max: 120, required: true }`
- hidden prompt fragment: `Happy birthday {{Возраст}}`
- user sees only input `Возраст`; backend renders the final hidden prompt.

MANDATORY CLEANUP:
This file is temporary. Delete `TEMP_PERSONALIZED_TREND_FIELDS_INSTRUCTION.md` from the feature branch after the feature and tests are complete and before merge.