# AURA

A local media library for videos, photos and music, designed for a keyboard or D-pad remote.

## Start the app

From this directory, run `python3 server.py` and open http://localhost:8080. Python 3.10 or newer is the only application dependency. Fonts, artwork, videos and music are included for offline use. Keep the server running while using the app, and open the HTTP address rather than the HTML file directly.

Use `python3 server.py --port 8081` to select another port. `--data-dir /absolute/path/to/library` selects a user library directory. Browser preferences belong to the exact hostname and port used to open the application.

## Add your media

### Import files or a folder

Choose **+** in the top bar, **Add your media** on Home, or press **O** while browsing. Select individual files or a folder. You can also drop files onto a browsing screen.

AURA copies imports to the local server's `data/` directory. Files remain available after a browser reload or server restart. Folder names become collections. The browser reads image dimensions and media duration and creates thumbnails when it can decode a file. A saved file with an unsupported codec is clearly reported.

**Stop import** or **Back** cancels the current transfer or preview operation; completed copies are kept. Imports are limited to 8 GiB per file and require enough local disk space. The browser and operating system provide the file picker. A sleep timer that expires during an import takes effect after the import finishes or is stopped.

### Connect existing folders without copying

```bash
python3 server.py \
  --media-dir "$HOME/Videos" \
  --media-dir "$HOME/Pictures" \
  --media-dir "$HOME/Music"
```

Include only folders that exist. Files appear under **Connected**, grouped by their parent folders. Connected folders are read-only. Use **Settings → Media library → Refresh connected folders** after changing files outside AURA. Hidden entries, symlinks and non-file entries are excluded; the scan is limited to 10,000 files.

### Open a direct media link

Choose **Add media → Open a media link**, paste an HTTP(S) media-file URL, and choose Video, Photo or Music. Links are saved in this browser; remote files are fetched directly by the browser when opened. The source provider can see those requests.

Use a direct file URL. Website pages, YouTube pages, DRM streaming services and account-protected pages are not integrated. External sources must permit browser access and use a supported format. External media always uses Direct sound.

## Browse your collection

**Home** highlights personal media and shows recent additions, resumable videos/music, photos and tracks. **Videos**, **Photos**, **Music** and **Saved** provide source filters, collection filtering, sorting and card density. Collection choices follow the current section and source.

**Search** matches titles, filenames and collection names. Type into the search field or use the on-screen keyboard with arrows and Enter. For large libraries, the first 200 matching items are displayed and the interface asks you to refine the search.

Open an item to view its details, play it or save it. Imported files can be renamed or assigned to another collection through **Manage media**. Deleting an import removes AURA's copy and its profile references; your original remains unchanged. Removing a media link changes browser data only. Connected-folder originals are never edited or deleted by AURA.

Alex, Guest and Family keep separate favorites and playback positions. The media library and general settings are shared. These are convenience profiles, without account authentication or parental restrictions.

## Watch, listen and view photos

### Video and music

The player includes play/pause, a real-duration seek bar, ten-second skips, previous/next items, resume, playback speed, repeat options, volume and mute. Video adds fit/fill, subtitles and fullscreen. Music shows album artwork alongside the actual audio player.

Controls can hide after the selected interval during playback. An arrow or Enter first reveals them; pointer movement also reveals them. Opening volume, subtitle, repeat or information dialogs preserves playback. Changing the audio path preserves position, pause state and subtitles for the current item. **Back** returns to details and then the originating card.

### Sound

**Direct** is the default sound path. It uses the browser's native media playback and AURA's real volume/mute controls. Press **M** to mute/unmute, or **+** to increase volume and unmute. Hardware and operating-system volume remain separate.

**Enhanced** processing is optional for local, imported and included media. It enables equalizer presets, bass, treble, balance, mono mixing and compression. Settings explain when these controls are saved for Enhanced playback. The sound sample and navigation feedback follow the selected processing path.

If the browser requests a user gesture, press Play. If playback is silent, check AURA's mute/volume indicator, the browser's site sound permission, the operating system's output device and your speaker volume. Physical speaker output depends on your own device setup.

### Subtitles

Open the **CC** control and choose an `.srt` or `.vtt` file. Captions follow the media timeline and use the chosen text size and background. Subtitle files stay in the current viewing session. Switching to another item clears them; changing audio processing for the same item preserves them. Embedded subtitle-track selection is not included.

### Photos

The photo viewer supports previous/next, timed slideshows, 90-degree rotation, fit/fill, zoom up to 3×, directional panning, favorites and file information. When zoomed, arrows pan; Back resets zoom before closing the viewer. Viewing transforms leave the original file intact. Slideshow progression pauses while an information dialog is open.

## Settings

Settings apply immediately and are saved automatically when browser storage is available. Slider dialogs show a live preview or current value; Back retains slider changes. Choice dialogs apply only when you select an option.

| Category | Controls |
| --- | --- |
| Picture | Preset, brightness, contrast, color intensity, temperature and video framing |
| Sound | Direct/Enhanced processing, volume, mute, EQ, bass, treble, balance, mono and navigation feedback |
| Appearance | Three backgrounds, four accents, halo/outline focus and clock options |
| Accessibility | Caption visibility, size/background, larger text, high contrast and reduced motion |
| Playback | Autoplay on open, resume, speed, control timeout, play-next, repeat and start screen |
| Photos | Fit/fill, slideshow interval and repeat |
| Media library | Included collection visibility, sorting, density, imports and connected-folder refresh |
| Profiles | Independent favorites and playback history |
| System | One-shot sleep timer, idle standby, manual standby, fullscreen and app information |
| Storage & privacy | History recording, scoped clearing, backup, restore and confirmed preference reset |

Picture settings change app images/video. Sound settings change AURA audio. Standby pauses AURA without powering off the computer or TV. Active video, music, slideshows and imports prevent idle standby. The explicit sleep timer still stops playback when it expires and returns to Off afterward.

## Keyboard and remote controls

| Key | Action |
| --- | --- |
| Arrow keys | Navigate rows and panes; adjust sliders or pan a zoomed photo |
| Enter / OK | Activate the focused control |
| Escape / BrowserBack / Backspace | Return; Backspace edits when a text field is focused |
| Tab / Shift+Tab | Traverse controls in the current page or dialog |
| Space | Play/pause in the player or photo viewer; activate a button in other dialogs |
| M / AudioVolumeMute | Mute or unmute |
| + / − / volume keys | Adjust AURA volume; volume-up also unmutes |
| S | Open Settings while browsing |
| / | Open Search while browsing |
| O | Open Add media while browsing |
| Home | Return Home while browsing |
| MediaPlayPause / MediaPlay / MediaPause | Control playback |
| MediaTrackNext / MediaTrackPrevious | Change the current item |
| MediaStop | Close playback |

In Settings, Up/Down selects a category, Right/Enter enters its remembered row, and Left returns to the categories. Back from a row first returns to its category. Choices use Up/Down and Enter. Sliders use Left/Right. Horizontal row ends stay within their row; vertical movement preserves grid position across shorter final rows. Focus scrolls into the owning pane and stays inside the current dialog.

A remote must emit browser keyboard events. Physical TV remotes, CEC integration, Bluetooth pairing and vendor TV SDKs are outside this browser app.

## Formats

The included collection contains three distinct 20–24-second photographic motion studies, five photos and three original stereo instrumentals. Each included video has WebM/VP9/Opus and MP4/H.264/AAC sources. Each track has Ogg/Opus and MP3 sources. AURA prefers a format reported as supported by the browser and can retry an alternate source if opening the first one fails.

The videos animate photographs with music; they are not full films or live-action launch footage. You can hide all included library items under **Settings → Media library → Show AURA collection**.

Import extensions include MP4/M4V, WebM, OGV, MOV, MKV; JPEG, PNG, WebP, GIF, AVIF, BMP; MP3, M4A, WAV, OGG, FLAC and Opus. Actual playback depends on the codecs inside the file and your browser. The app does not transcode your imports. HEVC, DTS, unusual MKV streams or HEIC images may need conversion outside AURA. Casting, surround passthrough and streaming-server integrations are not included.

## Storage and backups

- **Imported files and metadata:** the server's `data/` directory. Stop the server and copy that complete directory to back up your imports. `--data-dir` supports a permanent location outside the application folder.
- **Preferences, favorites, history and media links:** this browser's localStorage. Use **Settings → Storage & privacy → Back up preferences** to download JSON and **Restore a backup** to restore it.

The JSON backup does not contain media files or thumbnails. Restore validates the complete backup before changing live data. When existing browser state contains an invalid field, AURA repairs that field while retaining valid sections. Resetting AURA preferences keeps imported media and connected folders intact.

Keep the local server bound to localhost for normal use. The service uses same-origin checks and a per-session token for changes, restricts served paths and keeps connected folders read-only. No accounts, cloud uploads or analytics are part of the app.

## Optional Docker launch

```bash
docker compose up --build
```

The configuration uses a non-root Python service, a read-only application filesystem, a writable `aura-library` volume and a localhost-bound port. Stop with Ctrl+C, then `docker compose down`. Adding `-v` deletes the stored library volume.

## Developer checks

Development tools are optional. They are not application dependencies and their binaries are not included.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
python -m playwright install chromium
node --test tests/*.mjs
python -m unittest discover -s tests -p 'test_*.py' -v
```

Set `BROWSER_EXECUTABLE=/absolute/path/to/chromium` to use an existing Chromium executable. Browser HTTP suites start isolated servers and temporary libraries. `test_browser_extra.py` retains the explicitly mocked transport harness for additional File/Blob and audio graph checks; other browser suites use the actual HTTP app. Browser condition polling preserves the application's Content-Security-Policy. There are no runtime test controls in AURA.

`tools/build_collection.py` recreates the optional included media and alternative encodings. That developer script requires FFmpeg, NumPy, Pillow and scikit-image. The shipped media is ready to play without those tools.

## Credits

Application code, icons, original music and motion contributions: MIT (`LICENSE`). Photo source credits and license notices are in `THIRD_PARTY_NOTICES.md`. Local Inter and Outfit font files and their SIL Open Font License texts are under `assets/fonts/`.
