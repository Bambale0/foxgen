# Reference memory product contract

The feature is considered user-visible only when `📚 Память реф` is reachable from every generation screen that can consume saved images. The library must never display a control that can lead to an unsupported provider payload.

User actions are explicit: save, select/unselect, apply, delete, back. Merely uploading an image into a normal generation draft does not persist it. The `💾 Сохранить загруженные` action is the explicit bridge from a temporary draft into durable memory.

Applying a library selection changes only the current generation draft. Deleting from memory changes the durable library and may invalidate old drafts that still reference that UUID; those drafts must fail closed before provider submission.
