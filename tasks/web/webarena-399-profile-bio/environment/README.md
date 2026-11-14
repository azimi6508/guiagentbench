# Postmill application image

`Dockerfile` builds on the digest-pinned WebArena-Verified reddit image
(`am1n3e/webarena-verified-reddit`), which contains the full Postmill forum and
its seeded PostgreSQL database. The first build downloads that base image; it is
large, so allow time and disk space for it.

- `patch.py` adds the single fault hook to Postmill's `editBiography` controller
  action and asserts that it changes exactly one statement. When the mounted
  `/settings.json` has `drop_biography_save: true`, the previous biography is
  restored before the save is flushed; Postmill still redirects and shows its
  success message. `lineage/UserController.original.php` and
  `lineage/UserController.patched.php` record the controller before and after.
- `app.py` starts PostgreSQL on a container-local Unix socket and the PHP server
  on loopback, then serves `http://app:8000/`. It implements the framework's
  reset handshake (`POST /reset` with `X-GAB-Session`), rejects requests from
  older sessions, restores the initial biography and clears PHP sessions on
  reset. Only the profile, the biography editor and static assets are routed;
  other forum pages return 403.
- `router.php` signs every request in as the fixed WebArena test account.

The database needs a writable filesystem, so `task.toml` declares
`app_writable_root = true`: each trial gets a disposable writable container
layer, and every other container restriction still applies. Startup takes up to
about 90 seconds, which `reset_timeout_sec` in `[integration.web]` allows for.
