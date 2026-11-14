"""Trusted Markor fixture for this task; never exposed to evaluated agents."""
import io
import re

PACKAGE = 'net.gsantner.markor'


class Application:
    def __init__(self, settings):
        allowed = {'note_name', 'initial_text', 'expected_text', 'lose_note_on_restart'}
        if not isinstance(settings, dict) or set(settings) != allowed:
            raise ValueError('Invalid note-persistence fixture settings')
        if not isinstance(settings['note_name'], str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,60}\.txt', settings['note_name']):
            raise ValueError('Use a simple note filename inside Documents')
        for field in ('initial_text', 'expected_text'):
            if not isinstance(settings[field], str) or len(settings[field].encode()) > 16_384:
                raise ValueError('Invalid note fixture text')
        if type(settings['lose_note_on_restart']) is not bool:
            raise ValueError('The restart fault setting must be boolean')
        self.settings = dict(settings)
        self.note = '/sdcard/Documents/' + settings['note_name']

    def launch(self, device, adb):
        adb('shell', 'am', 'start', '-W', '-n', PACKAGE + '/.activity.DocumentActivity',
            '-a', 'android.intent.action.EDIT', '-d',
            'file:///storage/emulated/0/Documents/' + self.settings['note_name'], '-t', 'text/plain')

    def reset(self, device, adb):
        # Shared device/app state has already been cleared by the platform.
        adb('shell', 'appops', 'set', PACKAGE, 'MANAGE_EXTERNAL_STORAGE', 'allow')
        device.app_start(PACKAGE, stop=True)
        for _ in range(4):
            device(description='NEXT').click(timeout=10)
        device(resourceId=PACKAGE + ':id/done').click(timeout=10)
        if device(text='OK').wait(timeout=2):
            device(text='OK').click()
        device.app_stop(PACKAGE)
        adb('shell', 'mkdir', '-p', '/sdcard/Documents')
        device.push(io.BytesIO(self.settings['initial_text'].encode()), self.note)
        self.launch(device, adb)

    def reload(self, device, adb):
        # Perform the normal save/close first; the faulty fixture then models
        # loss of this task's note before reopening. No failed action is replayed.
        device.press('back')
        device.press('back')
        device.app_stop(PACKAGE)
        if self.settings['lose_note_on_restart']:
            device.push(io.BytesIO(b''), self.note)
        self.launch(device, adb)

    def check(self, device, adb):
        # Private gold verification only. GUI tools cannot call this method.
        return adb('shell', 'cat', self.note) == self.settings['expected_text']
