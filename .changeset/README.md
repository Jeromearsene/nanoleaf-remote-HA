# Changesets

Every pull request that changes what users get (`custom_components/` or
`hapble/`) adds one small file here, saying **how big the change is** and
**what to put in the changelog**. Tests, docs, CI and tooling changes need none.

```sh
python scripts/changeset.py new --bump patch -m "Fix the Remote not reconnecting after a reboot"
```

`--bump` is chosen by hand:

- `patch` — bug fix, no new behaviour
- `minor` — new feature, backwards compatible
- `major` — breaking change (users must do something when upgrading)

Several changesets can be pending at once: the release uses the highest bump.
See "Releasing" in `CONTRIBUTING.md`.
