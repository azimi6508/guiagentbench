Visual assertion contract `visual-v1` (web and native Android)

You choose what to check, when to check it, and which screenshots demonstrate
the expected appearance. No reference images or assertion regions are supplied
in advance. During authoring, call `gui_observe` with an optional `reference`
argument, for example `{"reference":"saved-note"}`. It returns the current
screenshot and saves those exact pixels under that name. Inspect it before
choosing it as a reference. You can capture several states during exploration.
An ordinary `gui_observe` without a reference only observes; it saves no baseline.

Each gui_observe includes the screenshot width and height, pixel units, top-left
origin (0, 0), and axes (x right, y down). Image regions and masks use these same
original-screenshot pixels. Coordinate actions also use these pixels wherever
the platform permits pointer interaction. Images are not resized by this contract.

Reference names use lowercase letters, numbers, hyphens and underscores, start
with a letter, and have at most 48 characters. Names are immutable: use a new
name for another capture. The framework preserves the named images; do not
encode images in Python, write image files, or supply paths/URLs to the API.

The executable assertion is:
`page.expect_image(reference, region=None, masks=None, threshold=0.1,
                   max_diff_pixels=0, include_aa=False, precondition=False,
                   observation_window_ms=1600)`

- `reference` is a name you captured with `gui_observe` during authoring.
- `region` is `[left, top, right, bottom]` in screenshot pixels, with right and
  bottom exclusive. None compares the whole viewport. Choose a region that
  covers the behavior you intend to verify.
- `masks` is a list of rectangles in the same viewport coordinates, entirely
  inside the comparison region. Mask only irrelevant dynamic content. Masked
  pixels are excluded; the assertion must retain some checked pixels.
- `threshold` is a per-pixel perceptual color tolerance in `[0, 1)`, not the
  fraction of the screen allowed to differ. Smaller values are more sensitive.
- `max_diff_pixels` is the maximum mismatching unmasked pixel count allowed.
  It must be smaller than the number of unmasked pixels. Select tolerances for
  harmless rendering variation without obscuring meaningful differences.
- `include_aa=False` ignores detected anti-aliasing differences; True counts them.
- `observation_window_ms` is an integer in 0..2000, default 1600. The broker
  takes five screenshot observations over that bounded window, at fractions
  0, .23, .51, .77 and 1, and compares every frame with the same sealed reference
  and your exact region, masks and tolerance. The assertion matches if any
  observed frame matches. A zero window takes one frame. Legacy direct wire
  requests without this field retain single-frame behavior. This is the
  `visual-observation-window-v1` measurement contract, not an action or trial
  retry. No action is repeated, reference learned, mask added or tolerance
  increased. Every observed PNG, timing, difference count and selected frame
  is retained. Observation errors remain fatal. Wall-clock/evidence budgets
  remain unchanged; use windows selectively for long tests. Do not use an
  earlier transient match to claim persistence: perform the relevant reopen
  or navigation before asserting the durable visible outcome.
- `precondition=True` identifies a positive screen/setup check. A mismatch there
  invalidates the submitted checks, not proof that the environment is broken.
  Use shared chrome independent of the goal, and reserve the destination,
  selected setting and saved content for behavioral assertions.

Example: after capturing an appropriate `saved-note` screenshot in authoring,
`page.expect_image("saved-note", region=[40, 200, 650, 400])` compares that region.
Choose coordinates from your own screenshots; these example coordinates are
not a task-specific solution. UI-capable arms may freely combine image and UI
assertions. Visual arms have only screenshot-based assertions.

Comparison uses pinned Pixelmatch Python and Pillow on screenshot pixels only.
It does not recognize text or interpret semantic correctness. Reference images
must themselves demonstrate the intended appearance. A visual match alone
cannot prove invisible backend state; establish relevant visible checkpoints
through the journey allowed by your arm.

Mobile screenshots can contain a blinking editor caret, selection handles,
fading scrollbars, focus indicators and system-bar time. These are visible
rendering details, not task outcome labels. The observation window accommodates
short-lived variation; it does not guarantee that arbitrary broad crops are
stable. Choose relevant regions and mask irrelevant dynamic areas using your
own permitted screenshots. A zero-tolerance comparison including changing
decoration can fail even when text/settings are correct. UI-capable arms may
use semantic checks when useful; no capability is mandatory.

References are frozen with the program before paired grading. The execution
API cannot create/update references, access another variant or return assertion
results. No reference is auto-created when missing. The broker records every
result and saves expected, actual, difference and original capture images for
review. Missing references, malformed images and invalid parameters invalidate
execution, even if the submitted program catches the exception.

At most 64 references, 4 MB per PNG and 32 MB total are retained. Exceeding these
limits fails explicitly; images are never silently pruned. Both paired runs use
the same reference bytes, names, regions, masks and comparison settings.
