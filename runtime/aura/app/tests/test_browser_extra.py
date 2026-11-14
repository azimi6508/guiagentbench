"""Additional explicitly harness-based media/file/signal checks.
No change to application runtime or browser policies.
"""
import unittest,json,os
from playwright.sync_api import sync_playwright
from browser_support import wait_for
from harness import mount,mock_uploads,ROOT
class ExtraMediaTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.p=sync_playwright().start();cls.b=cls.p.chromium.launch(executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,args=['--no-sandbox'])
 @classmethod
 def tearDownClass(cls):cls.b.close();cls.p.stop()
 def setUp(self):
  self.page=self.b.new_page(viewport={'width':1920,'height':1080});self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)));self.page.set_default_timeout(8000);mount(self.page)
 def tearDown(self):self.page.close();self.assertEqual(self.errors,[])
 def video(self):
  self.page.click('#nav-videos');self.page.click('#card-v-coffee');self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#media-element").currentTime>.5')
 def upload_files(self,names):
  mock_uploads(self.page);self.page.click('#nav-add');self.page.set_input_files('#media-files',[str(ROOT/p) for p in names]);wait_for(self.page,'(n)=>document.querySelector("#import-status").textContent.startsWith(n+" item")',arg=len(names),timeout=15000)
 def test_01_browser_decodes_imported_photo_video_audio(self):
  self.upload_files(['assets/photos/coffee.jpg','assets/media/liftoff.webm','assets/media/deep-field.ogg']);items=self.page.evaluate('__transport.items');self.assertEqual(len(items),3);self.assertEqual(items[0]['width'],600);self.assertGreater(items[1]['duration'],21);self.assertGreater(items[2]['duration'],23);self.assertEqual(items[1]['width'],1280);self.assertTrue(any(x['path'].endswith('/thumbnail') for x in self.page.evaluate('__transport.requests')));self.page.click('#import-done');self.page.click('#nav-videos');self.page.click('#source-import');self.page.locator('[data-action="detail"]').click();self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#media-element").currentTime>.5')
 def test_02_imported_photo_opens_and_can_be_renamed(self):
  self.upload_files(['assets/photos/coffee.jpg']);self.page.click('#import-done');self.page.click('#nav-photos');self.page.click('#source-import');self.page.locator('[data-action="detail"]').click();self.page.click('#detail-manage');self.page.click('#option-0');self.page.fill('#media-title','Family weekend');self.page.fill('#media-album','Our photographs');self.page.click('#edit-save');wait_for(self.page,'document.querySelector("#detail-title")?.textContent==="Family weekend"');self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#photo-image").naturalWidth===600')
 def test_03_delete_import_and_favorite_references(self):
  self.upload_files(['assets/photos/coffee.jpg']);self.page.click('#import-done');self.page.click('#nav-photos');self.page.click('#source-import');self.page.locator('[data-action="detail"]').click();self.page.click('#detail-save');self.page.click('#detail-manage');self.page.click('#option-1');self.page.click('#confirm-ok');wait_for(self.page,'__transport.items.length===0&&!document.querySelector("#detail-title")');self.assertEqual(self.page.evaluate('__verify.getState().profiles.alex.watchlist'),[])
 def test_04_cancel_before_upload_complete(self):
  mock_uploads(self.page);self.page.evaluate('__transport.delay=5000');self.page.click('#nav-add');self.page.set_input_files('#media-files',str(ROOT/'assets/media/liftoff.webm'));self.page.click('#import-stop');wait_for(self.page,'document.querySelector("#import-status").textContent.includes("stopped")');self.assertEqual(self.page.evaluate('__transport.items.length'),0);self.assertTrue(self.page.locator('#import-done').is_enabled())
 def test_05_bad_format_is_saved_with_warning_not_false_success(self):
  mock_uploads(self.page);self.page.click('#nav-add');self.page.set_input_files('#media-files',{'name':'broken.webm','mimeType':'video/webm','buffer':b'not a video'});wait_for(self.page,'document.querySelector("#import-errors").textContent.includes("could not be decoded")');self.assertEqual(self.page.evaluate('__transport.items.length'),1);self.page.click('#import-done');self.page.click('#nav-videos');self.page.click('#source-import');self.page.locator('[data-action="detail"]').click();self.page.click('#detail-play');wait_for(self.page,'!document.querySelector("#playback-notice").hidden');self.assertTrue(self.page.locator('#playback-notice').inner_text())
 def test_06_decoded_native_audio_has_nonzero_signal(self):
  self.video()
  result=self.page.evaluate('''async()=>{const el=document.querySelector('#media-element'),stream=el.captureStream(),ctx=new AudioContext();await ctx.resume();const src=ctx.createMediaStreamSource(stream),a=ctx.createAnalyser();a.fftSize=2048;src.connect(a);await new Promise(r=>setTimeout(r,600));const samples=new Float32Array(2048);a.getFloatTimeDomainData(samples);const result={tracks:stream.getAudioTracks().length,rms:Math.sqrt(samples.reduce((s,x)=>s+x*x,0)/samples.length)};src.disconnect();await ctx.close();return result;}''')
  print('NATIVE_DECODED_AUDIO',json.dumps(result));self.assertGreater(result['tracks'],0);self.assertGreater(result['rms'],.005)
 def test_07_enhanced_audio_signal_and_muting(self):
  self.page.click('#nav-settings');self.page.click('#settings-tab-sound');self.page.click('#setting-audioPath');self.page.click('#choice-enhanced');self.page.keyboard.press('Escape');self.video();self.page.wait_for_timeout(500);before=self.page.evaluate('__verify.audio.level()');self.assertIn('Enhanced',self.page.locator('#player-audio-status').inner_text());self.assertGreater(before,.005);self.page.keyboard.press('m');self.page.wait_for_timeout(350);after=self.page.evaluate('__verify.audio.level()');print('ENHANCED_AUDIO',json.dumps({'beforeRms':before,'mutedRms':after}));self.assertLess(after,.0001)
 def test_08_controls_hide_first_arrow_only_reveals(self):
  self.video();wait_for(self.page,'__verify.getPlayer().hidden',timeout=8000);t=self.page.locator('#media-element').evaluate('(e)=>e.currentTime');self.page.keyboard.press('ArrowRight');self.assertFalse(self.page.evaluate('__verify.getPlayer().hidden'));self.assertEqual(self.page.evaluate('document.activeElement.id'),'player-toggle');self.assertLess(abs(self.page.locator('#media-element').evaluate('(e)=>e.currentTime')-t),1)
 def test_09_repeat_one_restarts_same_file(self):
  self.video();self.page.evaluate("__verify.setting('repeatMode','one')");src=self.page.locator('#media-element').get_attribute('src');self.page.locator('#media-element').evaluate('(e)=>e.currentTime=e.duration-.1');wait_for(self.page,'document.querySelector("#media-element").currentTime<2');self.assertEqual(self.page.locator('#media-element').get_attribute('src'),src)
 def test_10_play_next_uses_next_actual_file(self):
  self.video();self.page.evaluate("__verify.setting('playNext',true)");self.page.locator('#media-element').evaluate('(e)=>e.currentTime=e.duration-.1');wait_for(self.page,'document.querySelector("#player-title").textContent==="Into the deep field"');wait_for(self.page,'document.querySelector("#media-element").currentTime>.2')
 def test_11_accessibility_picture_and_density_effects(self):
  self.page.click('#nav-settings');self.page.click('#settings-tab-access');self.page.click('#setting-highContrast');self.page.click('#setting-largeText');self.page.click('#setting-reducedMotion');self.assertTrue(self.page.locator('html').evaluate('(e)=>e.classList.contains("large-text")&&e.classList.contains("high-contrast")&&e.classList.contains("reduce-motion")'));self.page.click('#settings-tab-library');self.page.click('#setting-thumbnailSize');self.page.click('#choice-compact');self.assertEqual(self.page.locator('html').get_attribute('data-density'),'compact')
 def test_12_sleep_is_one_shot_and_preserves_files(self):
  self.page.evaluate('__verify.setSleep(Date.now()-10)');self.page.wait_for_selector('#wake');self.assertEqual(self.page.evaluate('__verify.getState().settings.sleepMinutes'),0);self.page.click('#wake');self.page.wait_for_timeout(500);self.assertEqual(self.page.locator('#wake').count(),0)
if __name__=='__main__':unittest.main(verbosity=2)
