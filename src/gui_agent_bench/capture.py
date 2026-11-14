"""Execute an admitted reference test in a trusted, private worker only."""

import argparse
from pathlib import Path
import runpy

from gui_agent_bench.adapters.factory import adapter_for
from gui_agent_bench.io import digest, dump


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--viewport-width', type=int, default=1280)
    parser.add_argument('--viewport-height', type=int, default=720)
    parser.add_argument('--timezone', default='UTC')
    parser.add_argument('--platform', choices=['web', 'mobile', 'tv'], default='web')
    parser.add_argument('--profile', default='generic')
    parser.add_argument('--preparation', default='{}')
    args = parser.parse_args()
    from gui_agent_bench.environment import decode_preparation
    from gui_agent_bench.tv import checkpoint_count

    source = runpy.run_path('/private/test_source.py')
    test = source['test_behavior']
    expected = checkpoint_count(source)
    frames, steps = [], []
    adapter = adapter_for(
        args.platform,
        args.url,
        (args.viewport_width, args.viewport_height),
        args.timezone,
        args.profile,
        decode_preparation(args.preparation),
    )

    def checkpoint(description):
        data = adapter.observe()
        index = len(frames) + 1
        relative = f'screenshots/{index:04d}.png'
        path = args.evidence / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        frames.append({'path': relative, 'sha256': digest(data), 'index': index})
        steps.append(description)

    try:
        adapter.reset()
        try:
            test(adapter.page, checkpoint)
            verdict = 'PASS'
        except AssertionError as exc:
            verdict = 'FAIL'
            # Private diagnostics also survive setup failures before the final
            # checkpoint. They never enter the public evidence manifest.
            dump(
                args.result.with_name('reference-assertion.json'),
                {'message': str(exc), 'checkpoints_completed': len(frames)},
            )
            args.result.with_name('reference-assertion.png').write_bytes(adapter.observe())
        # Setup/navigation/crashes cannot be mistaken for a successful fault.
        if len(frames) != expected:
            raise ValueError('reference execution did not produce every declared checkpoint')
        dump(args.evidence / 'manifest.json', {'frames': frames})
        dump(args.evidence / 'steps.json', steps)
        dump(args.result, {'verdict': verdict})
    finally:
        adapter.close()


if __name__ == '__main__':
    main()
