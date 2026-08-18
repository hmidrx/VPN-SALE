# Telegram notification preference authorization boundary

Telegram notification preferences are customer state. A caller-supplied Telegram numeric ID is not, by itself, proof of customer identity and must not authorize preference reads or writes.

The production API therefore does not mount the legacy raw-ID customer preference router. The Telegram bot continues to read and update preferences through the private Telegram bridge, where the backend authenticates the bot service and resolves the Telegram subject through the existing trusted internal identity path.

This hardening does not change preference persistence, notification delivery, customer defaults, provider behavior, payments or website behavior. The legacy router module remains available to focused unit tests while it is not part of the production application surface; future cleanup may remove that module after verifying that no authenticated customer surface requires it.

Regression coverage must verify both sides of the boundary: the raw-ID route prefix is absent from the production application schema, and the private Telegram preference read/update routes remain registered.
