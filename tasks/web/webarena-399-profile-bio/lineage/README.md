# Source provenance

- `selected-task.json` is task 399 from WebArena's `config_files/test.raw.json`
  at revision `dce04686a56253aefba7b18a4fa0937cf1dc987b`, re-serialized without
  changes. The imported copy of that file had SHA-256
  `7b50386fd69163dbc05d615d834df4c6ed2c35596e97a1b10d17451c02537652`.
- The application is Postmill from
  `am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46`.
- `UserController.original.php` is `/var/www/html/src/Controller/UserController.php`
  from that image; `UserController.patched.php` is the result of
  `../environment/patch.py`. Only `editBiography` differs.
- `WEBARENA-LICENSE` (Apache-2.0) and `POSTMILL-LICENSE` (Zlib) are the
  upstream notices. Keep them when redistributing this task.

Identifiers and transformation notes are also recorded in `../task.toml`.
