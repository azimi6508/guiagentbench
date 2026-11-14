"""Focused remote/keyboard regressions against the real HTTP application.

The native application CSP, media decoding, local storage and transport remain
active. Geometry is measured from rendered controls, not inferred from CSS.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_support import wait_for

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import Library, Server, Handler


class QuietHandler(Handler):
    def log_message(self, format, *args):
        pass


class NavigationHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'],
        )

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = Server(('127.0.0.1', 0), QuietHandler, Library(Path(self.temp.name)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.server_stopped = False
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 720})
        self.page = self.context.new_page()
        self.page.set_default_timeout(6500)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        response = self.page.goto(self.origin)
        self.assertIn("script-src 'self'", response.headers['content-security-policy'])
        self.page.wait_for_selector('#nav-settings')
        wait_for(self.page, 'import("/src/media.js").then(module => module.serverReady)')

    def tearDown(self):
        self.context.close()
        if not self.server_stopped:
            self.stop_server()
        self.temp.cleanup()
        self.assertEqual(self.errors, [], 'Unexpected application JavaScript errors')

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.server_stopped = True

    def key(self, value):
        self.page.keyboard.press(value)

    def focus(self):
        return self.page.evaluate('document.activeElement.id')

    def state(self):
        return self.page.evaluate('import("/src/store.js").then(module => module.state)')

    def settings(self, category):
        self.page.click('#nav-settings')
        self.page.click('#settings-tab-' + category)

    def video(self):
        self.page.click('#nav-videos')
        self.page.click('#card-v-coffee')
        self.page.click('#detail-play')
        wait_for(self.page, 'document.querySelector("#media-element").currentTime > .2')

    def visual_rows(self, selector):
        geometry = self.page.locator(selector).evaluate_all('''elements => elements.map(el => {
            const rect = el.getBoundingClientRect();
            return {id:el.id, x:rect.x, y:rect.y + rect.height / 2};
        })''')
        rows = []
        for item in sorted(geometry, key=lambda item: (item['y'], item['x'])):
            row = next((row for row in rows if abs(row[0]['y'] - item['y']) < 8), None)
            if row is None:
                rows.append([item])
            else:
                row.append(item)
        return [[item['id'] for item in sorted(row, key=lambda item: item['x'])] for row in rows]

    def assert_focus_visible(self):
        geometry = self.page.evaluate('''() => {
            const element = document.activeElement;
            const rect = element.getBoundingClientRect();
            const clip = {left:0, top:0, right:innerWidth, bottom:innerHeight};
            for(let parent=element.parentElement; parent; parent=parent.parentElement){
                const style=getComputedStyle(parent), box=parent.getBoundingClientRect();
                if(/auto|scroll|hidden|clip/.test(style.overflowX)){
                    clip.left=Math.max(clip.left,box.left+parent.clientLeft);
                    clip.right=Math.min(clip.right,box.left+parent.clientLeft+parent.clientWidth);
                }
                if(/auto|scroll|hidden|clip/.test(style.overflowY)){
                    clip.top=Math.max(clip.top,box.top+parent.clientTop);
                    clip.bottom=Math.min(clip.bottom,box.top+parent.clientTop+parent.clientHeight);
                }
            }
            return {id:element.id,focusable:element.matches('[data-focus]'),
                    rect:{left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom},clip};
        }''')
        self.assertTrue(geometry['focusable'], geometry)
        rect, clip = geometry['rect'], geometry['clip']
        self.assertGreaterEqual(rect['left'], clip['left'] - 1, geometry)
        self.assertGreaterEqual(rect['top'], clip['top'] - 1, geometry)
        self.assertLessEqual(rect['right'], clip['right'] + 1, geometry)
        self.assertLessEqual(rect['bottom'], clip['bottom'] + 1, geometry)

    def test_01_reverse_tab_without_current_control_enters_last_modal_control(self):
        self.settings('sound')
        self.page.click('#setting-volume')
        self.page.evaluate('document.activeElement.blur()')
        self.key('Shift+Tab')
        self.assertEqual(self.focus(), 'adjust-done')
        self.assert_focus_visible()
        self.page.evaluate('document.activeElement.blur()')
        self.key('Tab')
        self.assertEqual(self.focus(), 'adjust-range')
        self.key('Shift+Tab')
        self.assertEqual(self.focus(), 'adjust-done')
        self.assertEqual(self.page.locator('#shell').get_attribute('inert'), '')

    def test_02_wrapped_phone_header_follows_visual_rows_without_sideways_jumps(self):
        self.page.set_viewport_size({'width': 390, 'height': 844})
        rows = self.visual_rows('#header [data-focus]')
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(all(ident in ['nav-search', 'nav-add', 'nav-quick', 'nav-settings', 'nav-profile'] for ident in rows[0]), rows)
        self.assertEqual(rows[1], ['nav-home', 'nav-videos', 'nav-photos', 'nav-music', 'nav-saved'])
        for row in rows:
            self.page.focus('#' + row[0])
            for expected in row[1:]:
                self.key('ArrowRight')
                self.assertEqual(self.focus(), expected)
                self.assert_focus_visible()
            self.key('ArrowRight')
            self.assertEqual(self.focus(), row[-1], 'Right must not jump to another visual row')
        self.page.focus('#' + rows[0][0])
        self.key('ArrowDown')
        self.assertIn(self.focus(), rows[1])
        self.key('ArrowUp')
        self.assertEqual(self.focus(), rows[0][0])

    def test_03_search_action_row_is_stable_and_remote_can_reach_results(self):
        for width, height in [(800, 600), (390, 844)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.page.click('#nav-search')
                self.page.fill('#search-input', 'coffee')
                self.assertEqual(self.visual_rows('.keyboard-actions [data-focus]'), [['key-space', 'key-delete', 'key-clear']])
                self.key('Enter')
                self.assertEqual(self.focus(), 'key-A')
                for _ in range(5):
                    self.key('ArrowDown')
                self.assertEqual(self.focus(), 'key-4')
                self.key('ArrowDown')
                # Returning to a zone intentionally remembers its last control.
                action_ids = ['key-space', 'key-delete', 'key-clear']
                self.assertIn(self.focus(), action_ids)
                for _ in range(action_ids.index(self.focus())):
                    self.key('ArrowLeft')
                self.assertEqual(self.focus(), 'key-space')
                self.key('Enter')
                self.assertEqual(self.page.locator('#search-input').input_value(), 'coffee ')
                self.key('ArrowRight')
                self.assertEqual(self.focus(), 'key-delete')
                self.key('Enter')
                self.assertEqual(self.page.locator('#search-input').input_value(), 'coffee')
                self.key('ArrowRight')
                self.assertEqual(self.focus(), 'key-clear')
                self.key('Enter')
                self.assertEqual(self.page.locator('#search-input').input_value(), '')
                self.key('ArrowRight')
                self.assertTrue(self.focus().startswith('result-'), self.focus())
                self.assert_focus_visible()
                self.key('ArrowLeft')
                self.assertTrue(self.focus().startswith('key-'), self.focus())
                self.assert_focus_visible()

    def test_04_remote_scroll_keeps_larger_controls_inside_settings_grids_and_dialogs(self):
        for width, height in [(800, 600), (1280, 720)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.settings('access')
                if not self.state()['settings']['largeText']:
                    self.page.click('#setting-largeText')
                self.page.click('#settings-tab-sound')
                setting_ids = self.page.locator('#settings-rows [data-focus]').evaluate_all('elements => elements.map(el => el.id)')
                self.assertIn(self.focus(), setting_ids)
                for _ in range(setting_ids.index(self.focus())):
                    self.key('ArrowUp')
                    self.assert_focus_visible()
                self.assertEqual(self.focus(), setting_ids[0])
                self.assert_focus_visible()
                for expected in setting_ids[1:]:
                    self.key('ArrowDown')
                    self.assertEqual(self.focus(), expected)
                    self.assert_focus_visible()
                self.page.click('#nav-photos')
                rows = self.visual_rows('.media-grid [data-focus]')
                self.page.focus('#' + rows[0][0])
                for row in rows[1:]:
                    self.key('ArrowDown')
                    self.assertEqual(self.focus(), row[0])
                    self.assert_focus_visible()
                self.settings('playback')
                self.page.click('#setting-playbackRate')
                choices = self.page.locator('.choice-list [data-focus]').evaluate_all('elements => elements.map(el => el.id)')
                index = choices.index(self.focus())
                for _ in range(index):
                    self.key('ArrowUp')
                self.assertEqual(self.focus(), choices[0])
                self.assert_focus_visible()
                for expected in choices[1:]:
                    self.key('ArrowDown')
                    self.assertEqual(self.focus(), expected)
                    self.assert_focus_visible()
                self.key('ArrowDown')
                self.assertEqual(self.focus(), 'adjust-cancel')
                self.assert_focus_visible()
                self.key('Escape')

    def test_05_space_activates_nested_dialog_without_starting_paused_video(self):
        self.video()
        self.key('Space')
        element = self.page.query_selector('#media-element')
        self.assertTrue(element.evaluate('el => el.paused'))
        self.page.click('#player-volume')
        self.key('ArrowDown')
        self.assertEqual(self.focus(), 'adjust-done')
        self.key('Space')
        self.assertEqual(self.page.locator('#adjust-range').count(), 0)
        self.assertTrue(self.page.evaluate('(original) => original === document.querySelector("#media-element")', element))
        self.assertTrue(element.evaluate('el => el.paused'))
        self.page.click('#player-subs')
        self.page.focus('#subtitle-toggle')
        before = self.state()['settings']['captions']
        self.key('Space')
        self.assertEqual(self.state()['settings']['captions'], not before)
        self.assertTrue(element.evaluate('el => el.paused'))
        self.assertTrue(self.page.locator('#sub-title').is_visible())

    def test_06_held_enter_and_back_do_not_repeat_actions_or_dismiss_nested_layers(self):
        self.settings('privacy')
        self.page.focus('#system-reset')
        self.page.keyboard.down('Enter')
        for _ in range(4):
            self.page.keyboard.down('Enter')
        self.assertEqual(self.page.locator('#confirm-title').count(), 1)
        self.assertEqual(self.focus(), 'confirm-cancel')
        self.page.keyboard.up('Enter')
        self.page.focus('#confirm-ok')
        self.page.keyboard.down('Enter')
        wait_for(self.page, 'document.querySelector("#confirm-ok") === null')
        for _ in range(4):
            self.page.keyboard.down('Enter')
        self.page.keyboard.up('Enter')
        self.assertEqual(self.page.locator('[data-modal-scope]').count(), 0)
        self.video()
        self.page.click('#player-volume')
        self.page.keyboard.down('Backspace')
        for _ in range(4):
            self.page.keyboard.down('Backspace')
        self.page.keyboard.up('Backspace')
        self.assertEqual(self.page.locator('#adjust-range').count(), 0)
        self.assertEqual(self.page.locator('#media-element').count(), 1)
        self.assertEqual(self.page.locator('#detail-title').count(), 1)
        self.key('Backspace')
        self.assertEqual(self.page.locator('#media-element').count(), 0)
        self.assertEqual(self.page.locator('#detail-title').count(), 1)

    def test_07_incomplete_last_grid_row_preserves_the_intended_higher_column(self):
        for width, height in [(1280, 720), (800, 600), (390, 844)]:
            with self.subTest(viewport=(width, height)):
                self.page.set_viewport_size({'width': width, 'height': height})
                self.page.click('#nav-photos')
                rows = self.visual_rows('.media-grid [data-focus]')
                self.assertGreater(len(rows[-2]), len(rows[-1]), rows)
                upper = rows[-2]
                intended = len(upper) - 1
                self.page.focus('#' + upper[max(0, intended - 1)])
                if intended:
                    self.key('ArrowRight')
                self.assertEqual(self.focus(), upper[intended])
                self.key('ArrowDown')
                self.assertEqual(self.focus(), rows[-1][-1])
                self.assert_focus_visible()
                self.key('ArrowUp')
                self.assertEqual(self.focus(), upper[intended], rows)
                self.assert_focus_visible()

    def test_08_removing_saved_link_works_offline_and_retains_useful_focus(self):
        self.page.click('#nav-add')
        self.page.click('#add-link')
        self.page.fill('#media-url', self.origin + '/assets/media/coffee.webm')
        self.page.fill('#link-name', 'Offline link')
        self.page.click('#link-submit')
        self.page.wait_for_selector('#detail-title')
        ident = self.state()['links'][0]['id']
        self.page.click('#detail-save')
        self.assertIn(ident, self.state()['profiles']['alex']['watchlist'])
        self.page.click('#detail-manage')
        self.page.click('#option-0')
        self.page.wait_for_selector('#confirm-ok')
        requests = []
        self.page.on('request', lambda request: requests.append(request.url) if '/api/' in request.url else None)
        self.stop_server()
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#detail-title") === null')
        self.assertEqual(self.state()['links'], [])
        self.assertNotIn(ident, self.state()['profiles']['alex']['watchlist'])
        self.assertEqual(self.page.locator('#card-' + ident).count(), 0)
        self.assertEqual(requests, [], 'Removing a browser-owned link must not require the offline server')
        self.assertTrue(self.page.evaluate('document.activeElement.matches("[data-focus]") && !document.activeElement.closest("[inert]")'))
        self.assert_focus_visible()


if __name__ == '__main__':
    unittest.main(verbosity=2)
