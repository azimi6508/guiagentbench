"""Real HTTP media integration checks with the production CSP enabled.

Run with `python tests/test_media_http.py`. Set BROWSER_EXECUTABLE to use an
installed Chromium; otherwise use Playwright's installed Chromium. Fixtures,
uploads, range delivery, decoder output and application fallback are real.
Only the failure-specific tests abort the selected original media request.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from playwright.sync_api import sync_playwright
from browser_support import wait_for

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import Handler, Library, Server


class QuietHandler(Handler):
    def log_message(self, *args):
        pass


# Read an actual decoded audio track, keeping the analyser disconnected from
# output so this measurement never mixes a second copy into browser playback.
NATIVE_SIGNAL = """async el=>{
 const stream=el.captureStream(),context=new AudioContext();
 let source;
 try{
  await context.resume();source=context.createMediaStreamSource(stream);
  const analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);
  await new Promise(resolve=>setTimeout(resolve,250));
  let rms=0;
  for(let i=0;i<4;i++){
   const data=new Float32Array(2048);analyser.getFloatTimeDomainData(data);
   rms=Math.max(rms,Math.sqrt(data.reduce((sum,n)=>sum+n*n,0)/data.length));
   await new Promise(resolve=>setTimeout(resolve,40));
  }
  return {tracks:stream.getAudioTracks().length,rms,source:el.currentSrc,time:el.currentTime};
 }finally{source?.disconnect();await context.close();for(const track of stream.getTracks())track.stop();}
}"""


class MediaHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,
            headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def start_server(self, port=0):
        self.library = Library(Path(self.temp.name) / 'data')
        self.server = Server(('127.0.0.1', port), QuietHandler, self.library)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.start_server()
        self.context = self.browser.new_context(viewport={'width': 1920, 'height': 1080})
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.goto(f'http://127.0.0.1:{self.server.server_port}')
        self.page.wait_for_selector('#nav-home')
        wait_for(self.page, 'async()=>{const m=await import("/src/media.js");return m.serverReady;}')

    def tearDown(self):
        self.context.close()
        self.stop_server()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def settings(self, tab):
        self.page.click('#nav-settings')
        self.page.click('#settings-tab-' + tab)

    def open_item(self, kind, ident):
        self.page.click('#nav-' + kind)
        self.page.click('#card-' + ident)
        self.page.click('#detail-play')
        wait_for(self.page, 'document.querySelector("#media-element").readyState>=2')

    def playing(self):
        wait_for(self.page, 'document.querySelector("#media-element").currentTime>.25')

    def assert_signal(self):
        result = self.page.locator('#media-element').evaluate(NATIVE_SIGNAL)
        print('NATIVE_HTTP_AUDIO', json.dumps(result), flush=True)
        self.assertGreater(result['tracks'], 0)
        self.assertGreater(result['rms'], .003)
        return result

    def import_files(self, paths):
        self.page.click('#nav-add')
        self.page.set_input_files('#media-files', [str(ROOT / path) for path in paths])
        wait_for(self.page,
                 '(n)=>document.querySelector("#import-status").textContent.startsWith(n+" item")',
                 arg=len(paths), timeout=20000)
        self.assertEqual(self.page.locator('#import-errors').inner_text().strip(), '')

    def test_all_bundled_sources_decode_picture_and_sound_over_http(self):
        self.page.click('#nav-home')
        files = [p.name for p in sorted((ROOT / 'assets/media').iterdir()) if p.is_file()]
        results = self.page.evaluate("""async files=>{
         const results=[];
         for(const name of files){
          const video=/\\.(webm|mp4)$/.test(name),el=document.createElement(video?'video':'audio');
          el.preload='auto';el.volume=.7;el.style.cssText='position:fixed;width:32px;height:18px;left:0;top:0';document.body.append(el);
          let context,source,timer;
          try{
           el.src='/assets/media/'+name;
           await Promise.race([el.play(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('play timeout')),10000);})]);clearTimeout(timer);
           await new Promise(resolve=>setTimeout(resolve,400));
           const stream=el.captureStream();context=new AudioContext();await context.resume();source=context.createMediaStreamSource(stream);
           const analyser=context.createAnalyser();analyser.fftSize=2048;source.connect(analyser);await new Promise(resolve=>setTimeout(resolve,250));
           const samples=new Float32Array(2048);analyser.getFloatTimeDomainData(samples);
           const rms=Math.sqrt(samples.reduce((sum,n)=>sum+n*n,0)/samples.length);
           let mean=null;
           if(video){const canvas=document.createElement('canvas');canvas.width=32;canvas.height=18;const ctx=canvas.getContext('2d');ctx.drawImage(el,0,0,32,18);const pixels=ctx.getImageData(0,0,32,18).data;mean=pixels.reduce((sum,n,i)=>sum+(i%4===3?0:n),0)/(32*18*3);}
           results.push({name,time:el.currentTime,duration:el.duration,width:el.videoWidth||0,height:el.videoHeight||0,tracks:stream.getAudioTracks().length,rms,mean,error:el.error?.message||null});
           for(const track of stream.getTracks())track.stop();
          }catch(error){results.push({name,error:String(error),mediaError:el.error?.message});}
          finally{clearTimeout(timer);source?.disconnect();if(context)await context.close();el.pause();el.removeAttribute('src');el.load();el.remove();}
         }
         return results;
        }""", files)
        print('BUNDLED_HTTP_DECODE', json.dumps(results), flush=True)
        self.assertEqual(len(results), 12)
        for item in results:
            with self.subTest(file=item['name']):
                self.assertFalse(item.get('error'), item)
                self.assertGreater(item.get('time', 0), .25, item)
                self.assertGreater(item.get('rms', 0), .003, item)
                self.assertGreater(item.get('tracks', 0), 0, item)
                if item['name'].endswith(('.mp4', '.webm')):
                    self.assertEqual((item['width'], item['height']), (1280, 720))
                    self.assertGreater(item['mean'], 1)

    def test_real_ui_imports_probe_photo_video_and_music(self):
        self.import_files(['assets/photos/coffee.jpg', 'assets/media/liftoff.mp4', 'assets/media/coffee.mp3'])
        records = {item['name']: item for item in self.library.list()}
        self.assertEqual(len(records), 3)
        self.assertEqual((records['coffee.jpg']['width'], records['coffee.jpg']['height']), (600, 400))
        self.assertEqual((records['liftoff.mp4']['width'], records['liftoff.mp4']['height']), (1280, 720))
        self.assertGreater(records['liftoff.mp4']['duration'], 21)
        self.assertAlmostEqual(records['coffee.mp3']['duration'], 20, delta=.1)
        for name in ('coffee.jpg', 'liftoff.mp4'):
            self.assertTrue(records[name]['poster'].startswith('/thumb/'))
            self.assertGreater(self.library.resolve(records[name]['id'], thumbnail=True)[0].stat().st_size, 1000)
        self.page.click('#import-done')
        self.open_item('videos', records['liftoff.mp4']['id'])
        self.playing()
        self.assert_signal()

    def test_actual_server_restart_recovers_token_without_page_reload_or_duplicates(self):
        self.import_files(['assets/photos/coffee.jpg'])
        self.page.click('#import-done')
        ident = self.library.list()[0]['id']
        port, old_token = self.server.server_port, self.server.token
        self.stop_server()
        self.start_server(port)
        self.assertNotEqual(self.server.token, old_token)
        self.assertEqual(len(self.library.list()), 1)
        self.import_files(['assets/media/liftoff.mp4', 'assets/media/coffee.mp3'])
        self.assertEqual(len(self.library.list()), 3)
        self.page.click('#import-done')
        # Restart again so a metadata write independently has to refresh its token.
        self.stop_server()
        self.start_server(port)
        updated = self.page.evaluate("""async id=>{
         const m=await import('/src/media.js');
         await m.api('/api/media/'+id+'/metadata',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'Renamed after restart'})});
         return (await m.reloadLibrary()).items.find(item=>item.id===id);
        }""", ident)
        self.assertEqual(updated['title'], 'Renamed after restart')
        self.assertEqual(len(self.library.list()), 3)
        print('HTTP_SERVER_RESTART', json.dumps({'imports': 3, 'title': updated['title'], 'pageReloaded': False}), flush=True)

    def test_video_falls_back_to_mp4_and_preserves_selected_speed(self):
        self.settings('playback')
        self.page.click('#setting-playbackRate')
        self.page.click('[data-action="choose-setting"][data-value="1.5"]')
        self.page.keyboard.press('Escape')
        self.page.route('**/assets/media/coffee.webm', lambda route: route.abort())
        self.open_item('videos', 'v-coffee')
        self.playing()
        self.assertTrue(self.page.locator('#media-element').get_attribute('src').endswith('.mp4'))
        self.assertEqual(self.page.locator('#media-element').evaluate('(el)=>el.playbackRate'), 1.5)
        self.assertTrue(self.page.locator('#playback-notice').is_hidden())
        self.assert_signal()

    def test_music_falls_back_to_mp3_with_native_audio(self):
        self.page.route('**/assets/media/coffee.ogg', lambda route: route.abort())
        self.open_item('music', 'a-coffee')
        self.playing()
        self.assertTrue(self.page.locator('#media-element').get_attribute('src').endswith('.mp3'))
        self.assertTrue(self.page.locator('#playback-notice').is_hidden())
        self.assert_signal()

    def test_autoplay_off_fallback_stays_paused_and_clears_loading_notice(self):
        self.settings('playback')
        self.page.click('#setting-autoplay')
        self.page.keyboard.press('Escape')
        self.page.route('**/assets/media/coffee.webm', lambda route: route.abort())
        self.open_item('videos', 'v-coffee')
        wait_for(self.page, 'document.querySelector("#playback-notice").hidden')
        self.assertTrue(self.page.locator('#media-element').get_attribute('src').endswith('.mp4'))
        self.assertTrue(self.page.locator('#media-element').evaluate('(el)=>el.paused'))
        self.assertLess(self.page.locator('#media-element').evaluate('(el)=>el.currentTime'), .1)
        self.page.click('#player-toggle')
        self.playing()

    def test_paused_audio_path_change_keeps_position_and_open_subtitles(self):
        self.open_item('videos', 'v-coffee')
        self.playing()
        self.page.click('#player-toggle')
        self.page.click('#player-forward')
        wait_for(self.page, 'document.querySelector("#media-element").currentTime>=10')
        position = self.page.locator('#media-element').evaluate('(el)=>el.currentTime')
        self.page.click('#player-subs')
        self.page.set_input_files('#subtitle-file', {'name': 'remember.srt', 'mimeType': 'text/plain', 'buffer': b'1\n00:00:00,000 --> 00:00:20,000\nKeep these subtitles'})
        wait_for(self.page, 'document.querySelector("#subtitle-message").textContent.includes("loaded")')
        self.page.click('#subtitle-done')
        self.page.click('#player-more')
        self.page.click('#option-0')
        self.page.click('#option-1')
        wait_for(self.page, 'document.querySelector("#media-element").readyState>=2')
        self.assertTrue(self.page.locator('#media-element').evaluate('(el)=>el.paused'))
        self.assertAlmostEqual(self.page.locator('#media-element').evaluate('(el)=>el.currentTime'), position, delta=.15)
        wait_for(self.page, 'document.querySelector("#captions").textContent.includes("Keep these subtitles")')
        self.assertIn('Enhanced', self.page.locator('#player-audio-status').inner_text())

    def test_probe_can_be_canceled_while_loading(self):
        result = self.page.evaluate("""async()=>{
         const m=await import('/src/media.js'),data=await(await fetch('/assets/media/liftoff.mp4')).blob(),file=new File([data],'video.mp4',{type:'video/mp4'}),controller=new AbortController(),start=performance.now();
         const pending=m.probeFile(file,controller.signal);controller.abort();
         try{await pending;return {name:'not canceled'};}catch(error){return {name:error.name,elapsed:performance.now()-start};}
        }""")
        self.assertEqual(result['name'], 'AbortError')
        self.assertLess(result['elapsed'], 1000)

    def test_invalid_import_is_reported_and_player_shows_a_real_failure(self):
        self.page.click('#nav-add')
        self.page.set_input_files('#media-files', {'name': 'broken.webm', 'mimeType': 'video/webm', 'buffer': b'This is not a video file.'})
        wait_for(self.page, 'document.querySelector("#import-errors").textContent.includes("could not be decoded")')
        self.assertEqual(len(self.library.list()), 1)
        self.page.click('#import-done')
        self.page.click('#nav-videos')
        self.page.click('#card-' + self.library.list()[0]['id'])
        self.page.click('#detail-play')
        wait_for(self.page, '!document.querySelector("#playback-notice").hidden')
        self.assertGreater(self.page.locator('#media-element').evaluate('(el)=>el.error?.code||0'), 0)
        self.assertTrue(self.page.locator('#playback-notice').inner_text().strip())


if __name__ == '__main__':
    unittest.main(verbosity=2)
