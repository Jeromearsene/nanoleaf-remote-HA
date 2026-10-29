---
bump: patch
---

Battery saving mode: a hung read can no longer block the listener (8 s timeout), and a Remote that lets go of the connection after a pass is no longer treated as a failure. The end of a session is now logged.
