"""Public screenshot geometry; never infer targets or transform actions."""

import base64
import json
import struct


PIXEL_COORDINATES = (
    'Coordinates are integer pixels in the original screenshot, with top-left origin (0, 0). '
    'x increases right and y increases down. Use the screenshot width and height; '
    'coordinates are not percentages or a normalized 0-1000 scale. '
)
OBSERVE_DESCRIPTION = (
    'Get a screenshot plus its width, height, pixel units, origin and coordinate axes. ' + PIXEL_COORDINATES
)


def coordinate_instructions(viewport, platform='web'):
    width, height = viewport
    if any(type(n) is not int or n <= 0 for n in (width, height)):
        raise ValueError('positive integer screenshot dimensions required')
    dimensions = f'Screenshot dimensions: width={width} pixels, height={height} pixels. '
    bounds = f'Valid pixel positions: 0 <= x < {width}, 0 <= y < {height}. '
    if platform == 'tv':
        return (
            dimensions
            + PIXEL_COORDINATES
            + bounds
            + 'These coordinates describe image assertion regions only; TV interaction uses remote keys, not pointer actions.'
        )
    if platform not in {'web', 'mobile'}:
        raise ValueError('unknown coordinate platform')
    instructions = (
        dimensions
        + PIXEL_COORDINATES
        + bounds
        + 'click/hover x,y use these pixels directly, without automatic scaling. '
        'If you reason on a 0-1000 scale, convert to pixels before calling: '
        'x_pixel = floor(x_normalized * width / 1000), '
        'y_pixel = floor(y_normalized * height / 1000).'
    )
    if platform == 'mobile':
        instructions += ' Mobile touch restrictions and unavailable hover still apply.'
    return instructions


def observation_content(png, viewport, platform):
    # Read geometry only. Existing image/evidence budgets remain at their
    # original enforcement points; this annotation adds no response-size cap.
    if len(png) < 33 or png[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
        raise ValueError('PNG screenshot dimensions required')
    width, height = struct.unpack('>II', png[16:24])
    if (width, height) != tuple(viewport):
        raise ValueError('screenshot dimensions differ from the action viewport')
    metadata = {
        'width': width,
        'height': height,
        'units': 'pixels',
        'coordinate_space': 'original_screenshot',
        'origin': [0, 0],
        'x_axis': 'right',
        'y_axis': 'down',
    }
    return [
        {'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(png).decode()},
        {
            'type': 'text',
            'text': 'Screenshot coordinate metadata: '
            + json.dumps(metadata)
            + '\n'
            + coordinate_instructions((width, height), platform),
        },
    ]
