---
bump: patch
---

Fix the face numbers changing after a restart or an update: the 12 switch positions are now ordered by their GATT handle instead of the order BlueZ happens to return them in (which changes at every Home Assistant start). Calibrate the faces once more in Configure after updating.
