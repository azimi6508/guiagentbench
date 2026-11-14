"""Explicit platform selection for the trusted brokers and capture helpers."""


def adapter_for(platform, url, viewport, timezone, profile="generic", preparation=None):
    if platform == 'web':
        from gui_agent_bench.adapters.web import WebAdapter

        return WebAdapter(url, viewport, timezone, profile, preparation)
    if platform == 'mobile':
        from gui_agent_bench.adapters.mobile import MobileAdapter

        return MobileAdapter(url, viewport, timezone, profile)
    if platform == 'tv':
        if profile not in {'generic', 'tv'}:
            raise ValueError('unsupported TV profile')
        from gui_agent_bench.adapters.tv import TVAdapter

        return TVAdapter(url, viewport, timezone)
    raise ValueError('unsupported platform')
