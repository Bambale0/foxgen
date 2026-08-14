# Reference memory design notes

Reference memory intentionally reuses existing FoxGen boundaries instead of introducing another media subsystem:

- `LocalInputMediaStorage.describe()` reads an explicitly selected temporary input from the private shared ingress volume without creating a public URL or copying it locally again.
- `S3MediaStorage` owns the durable private object and signed URL generation.
- `reference_assets` owns durable user metadata and lifecycle.
- the existing shared `outbox_events` queue drives deletion recovery through the normal worker.
- Telegram FSM owns only browser position, transient selection and draft reference UUIDs.

A generated thumbnail derivative was not introduced because Telegram can render the original private image from a short-lived signed URL and the product requirement is a visual preview, not a transformed thumbnail asset. This avoids another image-processing dependency and derivative cleanup lifecycle while preserving a private preview.
