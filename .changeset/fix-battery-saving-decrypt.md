---
bump: patch
---

Battery saving mode: fix "ChaCha20-Poly1305 tag invalid" right after subscribing to the Remote's events. The Remote can deliver a response twice (as an indication and by read); the encrypted session now resynchronises its counter instead of failing.
