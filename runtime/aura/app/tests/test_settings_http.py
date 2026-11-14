"""Settings regressions against the real local HTTP application.

Uses native browser storage, the real server and media files, and normal CSP.
The browser clock is advanced only in timer tests; no app testing hooks,
transport mocks, autoplay overrides or disabled security policies are used.
"""
import json
import os
import re
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


def luminance(color):
    channels = [float(value) / 255 for value in re.findall(r'[\d.]+', color)[:3]]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return sum(channel * weight for channel, weight in zip(linear, [.2126, .7152, .0722]))


class SettingsHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'],
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
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.page = self.context.new_page()
        self.page.set_default_timeout(7000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        response = self.page.goto(self.origin)
        self.assertIn("script-src 'self'", response.headers['content-security-policy'])
        self.ready()

    def tearDown(self):
        self.context.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()
        self.assertEqual(self.errors, [], 'Unexpected JavaScript errors')

    def ready(self):
        self.page.wait_for_selector('#nav-settings')
        wait_for(self.page, 'import("/src/media.js").then(module => module.serverReady)')

    def state(self):
        return self.page.evaluate('import("/src/store.js").then(module => module.state)')

    def open_settings(self, category):
        self.page.click('#nav-settings')
        self.page.click('#settings-tab-' + category)

    def category(self, category):
        self.page.click('#settings-tab-' + category)

    def choose(self, key, value):
        self.page.click('#setting-' + key)
        self.page.click('#choice-' + str(value).replace('.', '-'))

    def key(self, value):
        self.page.keyboard.press(value)

    def restore(self, backup):
        self.open_settings('privacy')
        self.page.click('#system-import')
        self.page.set_input_files('#backup-file', {
            'name': 'preferences.json', 'mimeType': 'application/json',
            'buffer': json.dumps(backup).encode(),
        })
        wait_for(self.page, 'document.querySelector("#restore-title") === null')

    def open_video(self):
        self.page.click('#nav-videos')
        self.page.click('#card-v-coffee')
        self.page.click('#detail-play')
        wait_for(self.page, 'document.querySelector("#media-element").currentTime > .2')

    def test_01_every_setting_has_an_accessible_labeled_control(self):
        catalog = self.page.evaluate('''async () => {
            const {SETTINGS, definition} = await import('/src/settings.js');
            const {SCHEMA} = await import('/src/data.js');
            return {categories: SETTINGS.map(category => category.id),
                    settings: Object.entries(SCHEMA).map(([key, rule]) => ({...definition(key), boolean: rule === 'boolean'}))};
        }''')
        self.open_settings('picture')
        seen = set()
        for category in catalog['categories']:
            self.category(category)
            for setting in [row for row in catalog['settings'] if row['category'] == category]:
                control = self.page.locator('#setting-' + setting['key'])
                self.assertEqual(control.count(), 1)
                self.assertEqual(control.get_attribute('data-action'), 'open-setting')
                labels = control.get_attribute('aria-labelledby').split()
                descriptions = control.get_attribute('aria-describedby').split()
                for ident in labels + descriptions:
                    self.assertTrue(self.page.locator('#' + ident).inner_text().strip(), ident)
                if setting['boolean']:
                    self.assertEqual(control.get_attribute('role'), 'switch')
                    self.assertEqual(self.page.get_by_role('switch', name=setting['label'], exact=True).count(), 1)
                    self.assertEqual(control.get_attribute('aria-checked'), str(self.state()['settings'][setting['key']]).lower())
                else:
                    self.assertEqual(control.get_attribute('aria-haspopup'), 'dialog')
                seen.add(setting['key'])
        self.assertEqual(seen, {setting['key'] for setting in catalog['settings']})

    def test_02_keyboard_adjustments_persist_and_start_screen_is_honored(self):
        self.open_settings('picture')
        self.page.click('#setting-brightness')
        self.key('ArrowRight')
        self.key('ArrowRight')
        self.assertEqual(self.page.locator('#adjust-range').get_attribute('aria-valuetext'), '110%')
        self.assertAlmostEqual(float(self.page.locator('#adjust-range').evaluate("el => el.style.getPropertyValue('--range-progress').replace('%', '')")), 200 / 3)
        self.key('Escape')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'setting-brightness')
        self.category('appearance')
        self.choose('theme', 'slate')
        self.choose('accent', 'blue')
        self.page.click('#setting-showClock')
        self.category('playback')
        self.choose('startupPage', 'music')
        self.page.reload()
        self.ready()
        actual = self.state()['settings']
        self.assertEqual((actual['brightness'], actual['theme'], actual['accent'], actual['startupPage']), (110, 'slate', 'blue', 'music'))
        self.assertEqual(self.page.locator('#nav-music').get_attribute('aria-current'), 'page')
        self.assertTrue(self.page.locator('#header-clock').is_hidden())
        self.assertIn('brightness(1.1)', self.page.evaluate("document.documentElement.style.getPropertyValue('--picture')"))

    def test_03_theme_accent_focus_and_accessibility_change_rendered_styles(self):
        self.open_settings('appearance')
        backgrounds = []
        for theme in ['midnight', 'slate', 'oled']:
            self.choose('theme', theme)
            backgrounds.append(self.page.evaluate('getComputedStyle(document.body).backgroundColor'))
        self.assertEqual(len(set(backgrounds)), 3, backgrounds)
        outlines = []
        for accent in ['lavender', 'mint', 'amber', 'blue']:
            self.choose('accent', accent)
            self.page.focus('#setting-accent')
            outlines.append(self.page.locator('#setting-accent').evaluate('el => getComputedStyle(el).outlineColor'))
        self.assertEqual(len(set(outlines)), 4, outlines)
        self.choose('focusStyle', 'outline')
        self.page.focus('#setting-focusStyle')
        self.assertEqual(self.page.locator('#setting-focusStyle').evaluate('el => getComputedStyle(el).boxShadow'), 'none')
        self.category('access')
        selectors = ['#setting-captionSize .setting-text strong', '#setting-captionSize .setting-text > span', '.context-copy p']
        font_sizes = lambda: [float(self.page.locator(selector).evaluate('el => parseFloat(getComputedStyle(el).fontSize)')) for selector in selectors]
        before = font_sizes()
        self.page.click('#setting-largeText')
        after = font_sizes()
        for smaller, larger in zip(before, after):
            self.assertGreater(larger, smaller * 1.07)
        color = lambda: self.page.locator('#setting-captionSize .setting-text > span').evaluate('el => getComputedStyle(el).color')
        regular = color()
        self.page.click('#setting-highContrast')
        contrast = color()
        self.assertGreater(luminance(contrast), luminance(regular))
        self.page.click('#setting-reducedMotion')
        self.page.click('#nav-videos')
        self.page.focus('#card-v-coffee')
        motion = self.page.locator('#card-v-coffee .media-cover > img').evaluate('el => ({transform:getComputedStyle(el).transform, animation:getComputedStyle(el).animationName, transition:getComputedStyle(el).transitionDuration})')
        self.assertEqual(motion, {'transform': 'none', 'animation': 'none', 'transition': '0s'})
        self.page.click('#card-v-coffee')
        self.page.click('#detail-play')
        wait_for(self.page, 'document.querySelector("#media-element").currentTime > .2')

    def test_04_clearing_current_profile_and_resetting_category_are_scoped(self):
        backup = self.state()
        backup['settings'].update(volume=90, soundMode='cinema', bass=8, theme='slate', photoInterval=15)
        backup['profiles']['alex'] = {'watchlist': ['v-coffee'], 'history': {'v-coffee': {'time': 5, 'duration': 20, 'updated': 100}}}
        backup['profiles']['guest'] = {'watchlist': ['p-coffee'], 'history': {'v-liftoff': {'time': 7, 'duration': 22, 'updated': 101}}}
        guest = backup['profiles']['guest']
        self.restore(backup)
        self.open_settings('privacy')
        self.page.click('#system-clear-history')
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#system-clear-history").textContent.includes("0 saved")')
        self.assertEqual(self.state()['profiles']['alex']['history'], {})
        self.assertEqual(self.state()['profiles']['guest'], guest)
        self.assertEqual(self.state()['profiles']['alex']['watchlist'], ['v-coffee'])
        self.page.click('#system-clear-saved')
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#system-clear-saved").textContent.includes("0 saved")')
        self.assertEqual(self.state()['profiles']['guest'], guest)
        self.category('sound')
        self.page.click('#category-reset')
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#setting-value-volume").textContent === "65%"')
        actual = self.state()
        self.assertEqual((actual['settings']['volume'], actual['settings']['soundMode'], actual['settings']['bass']), (65, 'standard', 0))
        self.assertEqual((actual['settings']['theme'], actual['settings']['photoInterval']), ('slate', 15))
        self.assertEqual(actual['profiles']['guest'], guest)
        self.category('profiles')
        self.page.click('#settings-profile-guest')
        self.assertEqual(self.state()['profile'], 'guest')
        self.assertEqual(self.page.locator('#settings-profile-guest').get_attribute('aria-pressed'), 'true')
        self.page.click('#nav-saved')
        self.assertEqual(self.page.locator('[data-action="detail"]').count(), 1)
        self.assertTrue(self.page.locator('#card-p-coffee').is_visible())

    def test_05_sample_reset_mute_and_enhanced_path_have_live_effects(self):
        self.open_settings('sound')
        self.page.click('#sound-sample')
        wait_for(self.page, '[...document.querySelectorAll(".sound-bars i")].some(el => parseFloat(el.style.height) > 15)')
        self.assertEqual(self.page.locator('#sound-sample strong').inner_text(), 'Stop sound sample')
        self.page.click('#category-reset')
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#sound-sample strong").textContent === "Play sound sample"')
        wait_for(self.page, '[...document.querySelectorAll(".sound-bars i")].every(el => parseFloat(el.style.height) <= 9)')
        self.page.click('#setting-muted')
        self.page.click('#sound-sample')
        self.assertIn('Unmute AURA', self.page.locator('#toast').inner_text())
        self.assertIn('Audio muted', self.page.locator('#setting-description-volume').inner_text())
        self.page.click('#setting-muted')
        self.choose('audioPath', 'enhanced')
        self.choose('soundMode', 'cinema')
        self.assertNotIn('Used with Enhanced', self.page.locator('#setting-description-bass').inner_text())
        self.open_video()
        wait_for(self.page, 'document.querySelector("#player-audio-status").textContent.includes("Enhanced")')
        self.assertEqual(self.page.locator('#media-element').evaluate('el => el.volume'), 1)
        self.key('m')
        self.assertIn('Muted', self.page.locator('#player-audio-status').inner_text())
        self.key('+')
        self.assertFalse(self.state()['settings']['muted'])
        self.assertIn('70%', self.page.locator('#player-audio-status').inner_text())

    def test_06_clock_visibility_format_and_fullscreen_event_labels(self):
        self.open_settings('appearance')
        self.assertRegex(self.page.locator('#header-clock').inner_text(), r'[AP]M$')
        self.page.click('#setting-clock24')
        self.assertRegex(self.page.locator('#header-clock').inner_text(), r'^\d{2}:\d{2}$')
        self.page.click('#setting-showClock')
        self.assertTrue(self.page.locator('#header-clock').is_hidden())
        self.assertIn('hidden', self.page.locator('#setting-description-clock24').inner_text())
        self.page.click('#setting-showClock')
        self.assertTrue(self.page.locator('#header-clock').is_visible())
        self.category('system')
        self.page.click('#system-fullscreen')
        wait_for(self.page, 'document.fullscreenElement !== null')
        wait_for(self.page, 'document.querySelector("#system-fullscreen strong").textContent === "Exit fullscreen"')
        self.assertEqual(self.page.locator('#system-fullscreen strong').inner_text(), 'Exit fullscreen')
        self.page.evaluate('document.exitFullscreen()')
        wait_for(self.page, 'document.fullscreenElement === null')
        wait_for(self.page, 'document.querySelector("#system-fullscreen strong").textContent === "Enter fullscreen"')

    def test_07_sleep_off_cancels_countdown_and_standby_is_one_shot(self):
        self.page.clock.install()
        self.page.reload()
        self.ready()
        self.open_settings('system')
        self.choose('sleepMinutes', 5)
        self.choose('sleepMinutes', 0)
        self.page.clock.fast_forward(301000)
        self.assertEqual(self.page.locator('#wake').count(), 0)
        self.choose('sleepMinutes', 5)
        self.page.clock.fast_forward(301000)
        self.page.wait_for_selector('#wake')
        self.assertEqual(self.state()['settings']['sleepMinutes'], 0)
        self.page.click('#wake')
        self.assertEqual(self.page.locator('#setting-value-sleepMinutes').inner_text(), 'Off')
        self.page.clock.fast_forward(301000)
        self.assertEqual(self.page.locator('#wake').count(), 0)

    def test_08_idle_standby_waits_while_media_is_playing(self):
        self.page.clock.install()
        self.page.reload()
        self.ready()
        self.open_settings('system')
        self.choose('idleMinutes', 5)
        self.open_video()
        self.page.clock.fast_forward(301000)
        self.assertEqual(self.page.locator('#wake').count(), 0)
        self.key('Space')
        self.assertTrue(self.page.locator('#media-element').evaluate('el => el.paused'))
        self.page.clock.fast_forward(301000)
        self.page.wait_for_selector('#wake')
        self.assertEqual(self.page.locator('#media-element').count(), 0)
        self.assertEqual(self.state()['settings']['idleMinutes'], 5)

    def test_09_backup_export_roundtrip_and_factory_reset_preserve_imports(self):
        self.page.click('#nav-add')
        self.page.set_input_files('#media-files', str(ROOT / 'assets/photos/coffee.jpg'))
        wait_for(self.page, 'document.querySelector("#import-status").textContent.startsWith("1 item added")', timeout=15000)
        self.page.click('#import-done')
        imported = self.page.request.get(self.origin + '/api/library').json()['items']
        self.assertEqual(len(imported), 1)
        backup = self.state()
        backup['settings'].update(volume=85, theme='slate')
        backup['profiles']['guest']['watchlist'] = [imported[0]['id']]
        backup['links'] = [{'id': 'r_aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', 'title': 'Local link', 'kind': 'video', 'url': self.origin + '/assets/media/coffee.webm', 'added': 123}]
        self.restore(backup)
        self.open_settings('privacy')
        with self.page.expect_download() as download_info:
            self.page.click('#system-export')
        exported = json.loads(Path(download_info.value.path()).read_text())
        self.assertEqual(exported, self.state())
        self.assertEqual(exported['settings']['volume'], 85)
        self.page.click('#system-reset')
        self.page.click('#confirm-ok')
        wait_for(self.page, 'document.querySelector("#hero-play") !== null && document.querySelector("#confirm-ok") === null')
        actual = self.state()
        self.assertEqual(actual['settings']['volume'], 65)
        self.assertEqual(actual['links'], [])
        self.assertTrue(all(profile == {'watchlist': [], 'history': {}} for profile in actual['profiles'].values()))
        self.assertEqual(self.page.request.get(self.origin + '/api/library').json()['items'], imported)
        self.page.click('#nav-photos')
        self.page.click('#source-import')
        self.page.locator('[data-action="detail"]').click()
        self.page.click('#detail-play')
        wait_for(self.page, 'document.querySelector("#photo-image").naturalWidth === 600')

    def test_10_caption_preferences_change_loaded_subtitles_and_can_hide_them(self):
        self.open_settings('access')
        self.choose('captionSize', 'large')
        self.choose('captionBackground', 'solid')
        self.open_video()
        self.key('Space')
        self.page.click('#player-subs')
        self.page.set_input_files('#subtitle-file', {'name': 'captions.srt', 'mimeType': 'text/plain', 'buffer': b'1\n00:00:01,000 --> 00:00:18,000\nA real subtitle line'})
        wait_for(self.page, 'document.querySelector("#subtitle-message").textContent.includes("loaded")')
        self.page.click('#subtitle-done')
        self.page.locator('#media-element').evaluate('el => el.currentTime = 2')
        wait_for(self.page, 'document.querySelector("#captions").textContent === "A real subtitle line"')
        rendered = self.page.locator('#captions').evaluate('el => ({size:parseFloat(getComputedStyle(el).fontSize), base:parseFloat(getComputedStyle(document.documentElement).fontSize), background:getComputedStyle(el).backgroundColor})')
        self.assertAlmostEqual(rendered['size'] / rendered['base'], 2.5)
        self.assertEqual(rendered['background'], 'rgb(0, 0, 0)')
        self.page.click('#player-subs')
        self.page.click('#subtitle-toggle')
        self.page.click('#subtitle-done')
        self.assertTrue(self.page.locator('#captions').is_hidden())
        self.assertFalse(self.state()['settings']['captions'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
