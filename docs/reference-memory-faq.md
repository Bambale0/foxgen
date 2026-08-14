# Reference memory FAQ

**Does `/menu` clear saved references?** No. It clears the Redis draft and known temporary `inputs/` objects only.

**Can a saved reference be used by another user who guesses the UUID?** No. Resolve/delete are scoped to the authenticated internal Telegram user and only active rows are returned.

**Why are preview URLs stored nowhere in PostgreSQL?** They are short-lived capabilities generated on demand. PostgreSQL stores the private object key instead.

**Can saved photos be used in video generation?** Yes, when the selected video scenario accepts image inputs. The same capability limits used by normal uploads apply.

**Why is deletion asynchronous?** Metadata becomes unavailable atomically, while the worker retries the external S3 delete through the durable outbox without blocking the Telegram interaction.
