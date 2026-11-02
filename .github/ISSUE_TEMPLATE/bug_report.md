---
name: Bug report
about: Something doesn't work as documented
labels: bug
---

**Where does it happen?**
- [ ] Home Assistant integration
- [ ] Command-line tool (which command? e.g. `poetry run phase2`)

**Home Assistant integration**
- Home Assistant version and install type (OS, Container...):
- Integration version (HACS):
- Bluetooth adapter or ESPHome proxy used:
- Battery saving mode on or off:
- What you did and what happened instead:
- Debug logs (`logger: logs: custom_components.nanoleaf_remote: debug`) and the
  downloaded diagnostics file (pairing keys are redacted).

**Command-line tool**
- OS and Python version:
- Git commit or release you're on:
- Output with `BLEAK_LOGGING=1` set, if relevant.

**Logs and output**
Paste the complete output in a code block. Please double-check it doesn't
contain your 8-digit setup code or the contents of `pairing.json` (see
`SECURITY.md`) before pasting.

```
paste here
```

**What did you expect to happen?**

**Anything else?**
If your accessory is not the exact Nanoleaf Remote this project was built
against, describe it: real-hardware differences are useful signal, not just bugs.
