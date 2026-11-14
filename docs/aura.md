# AURA

AURA is a local media application with an offline starter collection, personal media imports, profiles, keyboard/D-pad navigation, playback and appearance/accessibility settings. Its complete application source is in `runtime/aura/app/`.

## Start the standalone application

```sh
python runtime/aura/app/server.py --port 8080
```

Open [http://localhost:8080](http://localhost:8080). Python 3.10 or newer is sufficient to run the app. No npm installation is needed for application use. Fonts, artwork, videos and music are bundled for offline use.

Keep the server running while using the app. Use `--port 8081` if another service occupies the default port. Open the HTTP address rather than the HTML file directly.

## Library and profiles

Import individual files or folders through the application, or connect read-only media directories:

```sh
python runtime/aura/app/server.py \
  --media-dir /absolute/path/to/videos \
  --media-dir /absolute/path/to/photos
```

Imported files are copied into the app's local `data/` directory. `--data-dir /absolute/path/to/library` selects another library. Connected-folder originals remain read-only. Keep local user libraries outside version control.

Alex, Guest and Family maintain separate favorites and playback positions. The library and general settings are shared. Browser preferences belong to the exact browser origin, so switching hostname or port uses a different preference store.

Use the on-screen add-media flow to import, connect or open direct media links. External media is requested by the browser. The application supports local video/music playback, photo viewing, search, source/collection filtering and saved media.

Keyboard controls and the complete application usage guide are in [the application README](../runtime/aura/app/README.md).

## Benchmark fixture

`runtime/aura/server.py` wraps the same application with a reproducible seed, session reset and the selected private mutation. It is a trusted environment component, outside evaluated workspaces.

The included task is `tv/aura-013-caption-preview-size`. It is classified in the TV domain and runs through the browser driver with all six arms. Build and check it with:

```sh
python scripts/bench.py build --task tv/aura-013-caption-preview-size
python scripts/bench.py run \
  --task tv/aura-013-caption-preview-size --arm test_ui \
  --model reference/solution
```

The standalone application server and the benchmark fixture server are separate entry points. Use the normal application server for personal media, and the framework controller for paired evaluation.

## Tests and licenses

The application has its own JavaScript, HTTP and browser tests under `runtime/aura/app/tests/`. JavaScript checks run with `node --test tests/*.mjs` from that directory. Python browser-test requirements are listed in `requirements-test.txt`.

AURA retains its MIT license. Preserve its third-party media and font notices, including the SIL Open Font License files under `assets/fonts/`. See [third-party notices](../THIRD_PARTY_NOTICES.md).
