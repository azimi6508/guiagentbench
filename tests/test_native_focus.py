from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from gui_agent_bench.mobile_driver import focused_package, wait_focused_package, Driver
from gui_agent_bench.failures import Failure


MARKOR = 'net.gsantner.markor'
MARKOR_ACTIVITY = 'net.gsantner.markor/net.gsantner.markor.activity.MainActivity'


def record(token, title, owner, uid=10217):
    # Shape of an API36 `dumpsys window` window record (captured on the AVD).
    return (
        f'  Window #3 Window{{{token} u0 {title}}}:\n'
        f'    mDisplayId=0 taskId=1231 mSession=Session{{b328b2d 31161:u0a10217}} mClient=android.os.BinderProxy@fdbf58d\n'
        + (f'    mOwnerUid={uid} showForAllUsers=false package={owner} appop=NONE\n' if owner else '')
        + '    mAttrs={(0,0)(fillxfill) ty=BASE_APPLICATION wanim=0x103030e\n'
        '      fl=SPLIT_TOUCH HARDWARE_ACCELERATED\n'
    )


def snapshot(token, title, *records):
    return (
        'WINDOW MANAGER WINDOWS (dumpsys window windows)\n'
        f'  mCurrentFocus=Window{{{token} u0 {title}}}\n'
        f'  mFocusedApp=ActivityRecord{{131256406 u0 {MARKOR}/.activity.MainActivity t1231}}\n'
        f'    mFocusedWindow=Window{{{token} u0 {title}}}\n' + ''.join(records)
    )


class NativeFocusTests(unittest.TestCase):
    def focus(self, text):
        with patch('gui_agent_bench.mobile_driver.adb', return_value=text) as adb:
            value = focused_package()
            adb.assert_called_once_with('shell', 'dumpsys', 'window', timeout=10)
            return value

    def assert_not_ready(self, text):
        with patch('gui_agent_bench.mobile_driver.adb', return_value=text):
            with self.assertRaises(Failure) as caught:
                focused_package()
            self.assertEqual(caught.exception.cause, 'app_not_ready')

    def test_exact_focused_window_wins_over_background_activity_records(self):
        clock = 'com.google.android.deskclock/com.android.deskclock.settings.SettingsActivity'
        text = snapshot(
            '1769cc0',
            clock,
            record('d86b342', MARKOR_ACTIVITY, MARKOR),
            record('1769cc0', clock, 'com.google.android.deskclock'),
        )
        self.assertEqual(self.focus(text), 'com.google.android.deskclock')

    def test_app_owned_popup_menu_resolves_to_its_owner(self):
        # Opening an app's overflow menu focuses a PopupWindow sub-window.
        text = snapshot(
            '32641cd',
            'PopupWindow:4df846c',
            record('32641cd', 'PopupWindow:4df846c', MARKOR),
            record('d86b342', MARKOR_ACTIVITY, MARKOR),
        )
        self.assertEqual(self.focus(text), MARKOR)

    def test_foreign_popup_or_dialog_reports_its_own_owner(self):
        text = snapshot(
            '5a5a5a5',
            'PopupWindow:77',
            record('d86b342', MARKOR_ACTIVITY, MARKOR),
            record('5a5a5a5', 'PopupWindow:77', 'com.android.systemui', uid=10123),
        )
        self.assertEqual(self.focus(text), 'com.android.systemui')
        text = snapshot('6b6b6b6', 'NotificationShade', record('6b6b6b6', 'NotificationShade', 'com.android.systemui'))
        self.assertEqual(self.focus(text), 'com.android.systemui')

    def test_owner_is_read_only_from_the_focused_record(self):
        # The next record's owner must not be borrowed by an ownerless record.
        text = snapshot(
            '32641cd',
            'PopupWindow:4df846c',
            record('32641cd', 'PopupWindow:4df846c', None),
            record('d86b342', MARKOR_ACTIVITY, MARKOR),
        )
        self.assert_not_ready(text)

    def test_missing_null_ambiguous_or_malformed_focus_fails_closed(self):
        valid = record('123', MARKOR + '/.activity.DocumentActivity', MARKOR)
        focus = f'  mCurrentFocus=Window{{123 u0 {MARKOR}/.activity.DocumentActivity}}\n'
        for text in (
            '',
            'mCurrentFocus=null\n',
            'topResumedActivity=ActivityRecord{123 u0 net.gsantner.markor/.Activity t1}',
            focus + focus + valid,
            'mCurrentFocus=Window{123 u0 ../../../private/labels}\n',
            focus,  # no window record
            focus + valid + valid,  # duplicate window record
            focus + record('123', MARKOR + '/.activity.DocumentActivity', 'evil..pkg'),
            focus + valid.replace('appop=NONE', 'package=com.other appop=NONE'),
        ):
            with self.subTest(text=text[:60]):
                self.assert_not_ready(text)

    def test_activity_title_must_agree_with_window_owner(self):
        text = snapshot('d86b342', MARKOR_ACTIVITY, record('d86b342', MARKOR_ACTIVITY, 'com.android.systemui'))
        self.assert_not_ready(text)

    def test_real_window_record_shape_from_research_avd(self):
        text = (
            '  mCurrentFocus=Window{32641cd u0 PopupWindow:4df846c}\n'
            '  mFocusedApp=ActivityRecord{131256406 u0 net.gsantner.markor/.activity.MainActivity t1231}\n'
            '  Window #7 Window{32641cd u0 PopupWindow:4df846c}:\n'
            '    mDisplayId=0 taskId=1231 mSession=Session{b328b2d 31161:u0a10217} mClient=android.os.BinderProxy@c1bcb64\n'
            '    mOwnerUid=10217 showForAllUsers=false package=net.gsantner.markor appop=NONE\n'
            '    mAttrs={(420,134)(294x144) gr=TOP START CENTER DISPLAY_CLIP_VERTICAL sim={state=unchanged adjust=resize} ty=APPLICATION_SUB_PANEL fmt=TRANSLUCENT\n'
            '      fl=LAYOUT_NO_LIMITS ALT_FOCUSABLE_IM WATCH_OUTSIDE_TOUCH SPLIT_TOUCH HARDWARE_ACCELERATED FLAG_LAYOUT_ATTACHED_IN_DECOR\n'
            '  Window #8 Window{d86b342 u0 net.gsantner.markor/net.gsantner.markor.activity.MainActivity}:\n'
            '    mOwnerUid=10217 showForAllUsers=false package=net.gsantner.markor appop=NONE\n'
        )
        self.assertEqual(self.focus(text), MARKOR)

    def test_declared_package_guard_rejects_foreign_foreground(self):
        driver = object.__new__(Driver)
        driver.package = 'org.example.editor'
        with patch('gui_agent_bench.mobile_driver.focused_package', return_value='com.android.systemui'):
            with self.assertRaises(Failure) as caught:
                driver.foreground()
            self.assertEqual(caught.exception.cause, 'app_scope_lost')

    def test_initial_focus_wait_is_bounded_and_accepts_only_target(self):
        with (
            patch(
                'gui_agent_bench.mobile_driver.focused_package',
                side_effect=['com.android.systemui', 'net.gsantner.markor'],
            ) as focus,
            patch('time.sleep'),
        ):
            wait_focused_package('net.gsantner.markor')
            self.assertEqual(focus.call_count, 2)
        with (
            patch('time.monotonic', side_effect=[0, 16]),
            patch('gui_agent_bench.mobile_driver.focused_package') as focus,
        ):
            with self.assertRaises(Failure):
                wait_focused_package('net.gsantner.markor')
            focus.assert_not_called()

    def test_focus_sample_returning_after_launch_deadline_cannot_succeed(self):
        with (
            patch('time.monotonic', side_effect=[0, 1, 16, 16, 16]),
            patch('time.sleep'),
            patch('gui_agent_bench.mobile_driver.focused_package', return_value='net.gsantner.markor'),
        ):
            with self.assertRaises(Failure):
                wait_focused_package('net.gsantner.markor')


if __name__ == '__main__':
    unittest.main()
