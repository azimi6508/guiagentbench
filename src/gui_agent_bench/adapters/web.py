"""Playwright primitives with explicit, bounded readiness and fresh resets."""

import hashlib
import time
import uuid
import urllib.error
import urllib.request

from gui_agent_bench.environment import emit, fingerprint, web_preparation
from gui_agent_bench.failures import Failure

INITIAL_TIMEOUT_MS = 10_000
RENDER_PAUSE_MS = 250


class WebAdapter:
    platform = 'web'

    def __init__(self, base_url: str, viewport=(1280, 720), timezone='UTC', profile='generic', preparation=None):
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

        self.profile = profile
        self.preparation = web_preparation(preparation)
        self.base_url = base_url.rstrip('/')
        self.playwright = sync_playwright().start()
        self._playwright_timeout_error = PlaywrightTimeoutError
        self.browser = self.playwright.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
        self.viewport, self.timezone = viewport, timezone
        self.context = None
        self.session = None
        self.reset_generation = 0
        self._fresh_context()

    def _close_context(self):
        if self.context:
            self.context.close()
        self.context = None
        self.page = None

    def _fresh_context(self):
        self._close_context()
        self.context = self.browser.new_context(
            viewport={'width': self.viewport[0], 'height': self.viewport[1]},
            device_scale_factor=1,
            service_workers='block',
            timezone_id=self.timezone,
            locale='en-US',
            extra_http_headers={'X-GAB-Session': self.session} if self.session else {},
        )
        self.context.route(
            '**/*',
            lambda route: route.continue_() if route.request.url.startswith(self.base_url + '/') else route.abort(),
        )
        self.context.route_web_socket('**/*', self._route_web_socket)
        self.page = self.context.new_page()
        self.page.set_default_timeout(30_000)
        self._prepare_clock()

    def _prepare_clock(self):
        # Date-only browser control leaves callbacks and controller deadlines real.
        epoch = self.preparation['fixed_clock']
        if epoch:
            from datetime import datetime

            self.page.clock.set_fixed_time(datetime.fromisoformat(epoch))
            emit(
                'clock', 'web', profile=self.profile, wall_clock=epoch, timer_mode='real', controller_clock='unchanged'
            )

    def _route_web_socket(self, socket):
        # WebSocket connections require an explicitly implemented application adapter.
        return

    def _require_context(self):
        if self.context is None or self.page is None:
            raise Failure('app_not_ready')

    def user_step(self, action: dict):
        self._require_context()
        started, target = time.monotonic(), None
        try:
            if action['action'] != 'reload':
                target = self.page.get_by_role(action['role'], name=action['name'], exact=True)
            self._user_step(action, target)
        except Exception as exc:
            # Observe only the already-permitted UI target. No action retry,
            # screenshot, raw DOM, exception text or selector is recorded.
            self.diagnose_target(exc, target, started)
            raise

    def _user_step(self, action, target):
        if action['action'] == 'reload':
            self.page.reload(wait_until='domcontentloaded')
        else:
            matches = target.count()
            if matches == 0:
                # Resolve before dispatch, as the native adapters do. This is
                # known target feedback, not a reinterpretation of an action
                # timeout. Keep Playwright's bounded wait for loading targets.
                from gui_agent_bench.failure_detail import attach

                try:
                    target.wait_for(state='attached')
                except self._playwright_timeout_error as exc:
                    raise attach(
                        Failure('target_unavailable'),
                        component='web_adapter',
                        stage='target_action',
                        facts={'pre_action_matches': 0, 'action_dispatched': False},
                    ) from exc
                matches = target.count()
            if matches == 0:
                raise attach(
                    Failure('target_unavailable'),
                    component='web_adapter',
                    stage='target_action',
                    facts={'pre_action_matches': 0, 'action_dispatched': False},
                )
            if matches > 1:
                raise Failure('target_ambiguous')
            if action['action'] == 'click':
                self._click_control(target, action['role'])
            elif action['action'] == 'hover':
                target.hover()
            elif action['action'] == 'fill':
                target.fill(action['text'])
            elif action['action'] == 'press':
                target.press(action['key'])
        self.wait_ready()

    def _click_control(self, target, role):
        # Some native toggles expose their accessible role but delegate pointer
        # activation to a visible label. Resolve before acting, never retry a
        # failed click. Only UI actions reach here; no DOM is returned to agents.
        if (
            role not in {'radio', 'checkbox'}
            or target.count() != 1
            or target.is_visible()
            or not target.is_enabled()
            or not target.evaluate("el => el.tagName === 'INPUT' && ['radio', 'checkbox'].includes(el.type)")
        ):
            return target.click()
        labels = target.evaluate_handle('el => Array.from(el.labels || [])')
        properties = {}
        facts = {'activation_target': 'native_control'}
        try:
            properties = labels.get_properties()
            visible = [
                handle.as_element()
                for handle in properties.values()
                if handle.as_element() is not None and handle.as_element().is_visible()
            ]
            facts.update(associated_labels=len(properties), visible_labels=len(visible))
            if len(visible) > 1:
                raise Failure('target_ambiguous')
            if visible:
                facts['activation_target'] = 'associated_label'
                return visible[0].click()
            return target.click()
        except Exception as exc:
            from gui_agent_bench.failure_detail import attach

            attach(exc, component='web_adapter', stage='target_action', facts=facts)
            raise
        finally:
            for handle in properties.values():
                try:
                    handle.dispose()
                except Exception:
                    pass  # Cleanup must not replace the action's failure.
            try:
                labels.dispose()
            except Exception:
                pass

    def diagnose_target(self, exc, target, started, stage='target_action'):
        from gui_agent_bench.failure_detail import attach

        elapsed = round((time.monotonic() - started) * 1000)
        facts = {'observation': 'after_failure'}
        try:
            facts['page_closed'] = self.page.is_closed()
            facts['browser_connected'] = self.browser.is_connected()
            if target is not None and not facts['page_closed']:
                count = target.count()
                facts['target_matches'] = count
                if count == 1:
                    facts['visible'] = target.is_visible()
                    facts['enabled'] = target.is_enabled(timeout=100)
                    # Read-only hit-test facts help distinguish visibility from
                    # pointer reachability. No element names or DOM leave here.
                    if facts['visible']:
                        facts.update(
                            target.evaluate(
                                '''e => {
                            const r = e.getBoundingClientRect();
                            const x = r.left + r.width / 2, y = r.top + r.height / 2;
                            const hit = document.elementFromPoint(x, y);
                            return {
                                center_in_viewport: x >= 0 && y >= 0 && x < innerWidth && y < innerHeight,
                                center_hits_target: !!hit && (hit === e || e.contains(hit)),
                                pointer_events_none: getComputedStyle(e).pointerEvents === 'none'
                            };
                        }'''
                            )
                        )
        except Exception:
            # Diagnosis must not replace the original failure.
            facts['probe_failed'] = True
        # Mocks and unsupported transports must never introduce arbitrary data.
        from gui_agent_bench.failure_detail import FACTS

        facts = {k: v for k, v in facts.items() if FACTS[k](v)}
        attach(exc, component='web_adapter', stage=stage, facts=facts, elapsed_ms=elapsed)

    def wait_ready(self, *, initial=False, timeout_ms=INITIAL_TIMEOUT_MS):
        """Verify initial preparation, or allow a short post-action render turn.

        No global motion/network/busy predicate: it would hide legitimate app
        states. This helper never asserts a task result or inspects fault labels.
        """
        self._require_context()
        if not initial:
            self.page.wait_for_timeout(RENDER_PAUSE_MS)
            return
        start = time.monotonic()
        deadline = start + timeout_ms / 1000

        def remaining():
            value = int((deadline - time.monotonic()) * 1000)
            if value <= 0:
                raise self._playwright_timeout_error('initial preparation deadline')
            return value

        try:
            self.page.wait_for_load_state('domcontentloaded', timeout=remaining())
            self.page.locator('body').wait_for(state='attached', timeout=remaining())
            for item in self.preparation['ready']:
                locator = (
                    self.page.get_by_test_id(item['test_id'])
                    if 'test_id' in item
                    else self.page.get_by_role(item['role'], name=item['name'], exact=True)
                )
                locator.wait_for(state='visible', timeout=remaining())
            if self.preparation['wait_for_fonts']:
                # Finish the initial local-font load within the existing deadline.
                # Never gate later observations/actions on layout or animation.
                self.page.wait_for_function("document.fonts.status === 'loaded'", timeout=remaining())
            remaining()
            return emit(
                'readiness',
                'web',
                status='ready',
                profile=self.profile,
                initial=True,
                elapsed_ms=round((time.monotonic() - start) * 1000),
            )
        except self._playwright_timeout_error as exc:
            emit('readiness', 'web', status='timeout', profile=self.profile, initial=True)
            raise Failure('app_not_ready') from exc
        except Exception:
            emit('readiness', 'web', status='error', profile=self.profile, initial=True)
            raise

    _wait_for_settled_page = wait_ready

    def reset(self):
        # Close old pages BEFORE resetting the backend so their timers cannot
        # issue requests into the next state. In-flight server work still needs
        # the app's reset synchronization contract.
        self._close_context()
        self.reset_generation += 1
        start = time.monotonic()
        try:
            self.session = uuid.uuid4().hex
            request = urllib.request.Request(
                self.base_url + '/reset', data=b'', method='POST', headers={'X-GAB-Session': self.session}
            )
            # One bounded reset request, sized by the task's declaration; a lost
            # response is never retried.
            reset_timeout = self.preparation['reset_timeout_sec']
            deadline = start + reset_timeout
            attempts = 0
            while True:
                attempts += 1
                try:
                    with urllib.request.urlopen(
                        request, timeout=max(0.1, min(reset_timeout, deadline - time.monotonic()))
                    ) as response:
                        if response.status not in {200, 204} or response.headers.get('X-GAB-Session') != self.session:
                            raise Failure('reset_failure')
                    break
                except urllib.error.HTTPError:
                    raise
                except urllib.error.URLError as exc:
                    # Only refused connections are safe startup polling. A lost
                    # response after sending reset has an unknown outcome.
                    if not isinstance(exc.reason, ConnectionRefusedError) or time.monotonic() >= deadline:
                        raise
                    time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            self._fresh_context()
            self.page.goto(self.base_url + '/', wait_until='domcontentloaded')
            self.wait_ready(initial=True)
            emit(
                'reset',
                'web',
                status='ready',
                profile=self.profile,
                generation=self.reset_generation,
                transport_attempts=attempts,
                screenshot_sha256=hashlib.sha256(self.page.screenshot(type='png')).hexdigest(),
                storage_sha256=fingerprint(self.context.storage_state()),
                viewport=list(self.viewport),
                locale='en-US',
                timezone=self.timezone,
                clock=self.preparation['fixed_clock'] or 'realtime',
            )
        except Exception as exc:
            self._close_context()
            emit('reset', 'web', status='error', profile=self.profile, generation=self.reset_generation)
            raise Failure('reset_failure') from exc

    def open_url(self, url: str):
        self._require_context()
        if url != self.base_url + '/':
            raise ValueError('URL is outside the application home-page allowlist')
        self.page.goto(url, wait_until='domcontentloaded')
        self.wait_ready()

    def observe(self) -> bytes:
        self._require_context()
        return self.page.screenshot(type='png')

    def dump_ui(self):
        self._require_context()
        return self.page.locator('body').aria_snapshot()

    def install_app(self, _artifact):
        raise NotImplementedError('APK installation is not a web capability')

    def close(self):
        self.browser.close()
        self.playwright.stop()
