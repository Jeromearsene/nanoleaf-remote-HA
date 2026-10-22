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
- Bluetooth adapter or ESPHome proxy used:
- Integration version (HACS):
- Debug logs (`logger: logs: custom_components.nanoleaf_remote: debug`) and the
  downloaded diagnostics file (pairing keys are redacted).

**Full output**
Paste the complete output (terminal or Home Assistant log) in a code block.
Please double-check it doesn't contain your 8-digit setup code or the
contents of `pairing.json` (see `SECURITY.md`) before pasting.

```
paste here
```

**Environment**
- OS: (Windows / macOS / Linux, + version)
- Python version: (`python3 --version`)
- Git commit or release you're on:

**What did you expect to happen?**

**Anything else?**
If relevant, output with `BLEAK_LOGGING=1` set, or a description of your
accessory if it's not the exact Nanoleaf Remote this project was built
against — real-hardware differences are useful signal, not just bugs.
