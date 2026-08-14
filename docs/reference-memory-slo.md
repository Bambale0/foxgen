# Reference memory service expectations

Reference library browsing and mutation are control-plane operations and must not create provider tasks or wallet mutations. A failure to list/save/delete a reference leaves the user in a recoverable Telegram flow.

The final generation boundary remains the existing paid admission path. Reference resolution happens immediately before payload construction and therefore must fail before a provider side effect if ownership or asset state is no longer valid.
