# Media sources and licenses

The original application, SVG interface icons, original instrumental scores and motion/editing contributions are MIT licensed under `LICENSE`. The photographs below retain their own public-domain/CC0 status. Their inclusion does not imply an endorsement of AURA by a photographer, person pictured, NASA, ESA, STScI, SpaceX, or Pikolo Espresso Bar.

These copies were obtained from the installed scikit-image example-data collection. The upstream dataset documentation identifies their sources and licenses:

https://scikit-image.org/docs/stable/api/skimage.data.html

| Packaged file | Dataset source | Credit and status documented upstream |
| --- | --- | --- |
| `assets/photos/liftoff.jpg` | `skimage.data.rocket()` | SpaceX photograph of Falcon 9 / DSCOVR; released into the public domain |
| `assets/photos/deep-field.jpg` | `skimage.data.hubble_deep_field()` | NASA Hubble eXtreme Deep Field, downloaded from HubbleSite; public domain per upstream data documentation. Credit: NASA / ESA / STScI |
| `assets/photos/portrait.jpg` | `skimage.data.astronaut()` | NASA astronaut portrait of Eileen Collins; public domain |
| `assets/photos/coffee.jpg` | `skimage.data.coffee()` | Rachel Michetti, courtesy of Pikolo Espresso Bar; CC0 |
| `assets/photos/chelsea.jpg` | `skimage.data.chelsea()` | Stefan van der Walt; CC0 |

CC0 legal instrument: https://creativecommons.org/publicdomain/zero/1.0/

NASA image/media usage guidance: https://www.nasa.gov/nasa-brand-center/images-and-media/

The JPEG copies are re-encoded from those images. The application may crop, resize or apply user-selected picture effects at display time. The three video studies, each supplied in two formats in `assets/media/`, add slow zoom/pan, fade and original music to the corresponding photograph. The names “Before liftoff”, “Into the deep field” and “A slower morning” identify those short photographic studies, not third-party movies. They should not be represented as live-action footage.

The `.ogg` and `.mp3` files contain only original AURA instrumental music. Their associated cover images retain the credits above. The `.webm` and `.mp4` files contain that original music plus the credited photographs. Preserve these notices when redistributing the collection.

Python, Chromium, Playwright, FFmpeg, NumPy, Pillow and scikit-image are external runtime/development tools with their own licenses. Their executables and libraries are not included in this repository. FFmpeg, NumPy, Pillow and scikit-image are needed only to recreate the optional bundled collection with `tools/build_collection.py`, not to run or use AURA.


## Bundled fonts

The unmodified Latin variable WOFF2 subsets of Inter (© 2016 The Inter Project Authors) and Outfit (© 2021 The Outfit Project Authors) in `assets/fonts/` are licensed under the SIL Open Font License, Version 1.1. The license texts are included as `assets/fonts/OFL-Inter.txt` and `assets/fonts/OFL-Outfit.txt`, with a summary in `assets/fonts/NOTICE.txt`. Preserve these files when redistributing the fonts. Font fallback uses locally available system fonts for characters outside the included subsets.
