"""Browser acceptance checks. HTTP by default; AURA_INLINE=1 is an explicit
Storage/API-mocked about:blank harness for managed-browser environments.
"""
import json,os,sys,tempfile,threading,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_support import wait_for
from harness import ROOT,mount,uri
sys.path.insert(0,str(ROOT))
from server import Library,Server,Handler
INLINE=os.environ.get('AURA_INLINE')=='1'
class BrowserTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,headless=True,args=['--no-sandbox'])
 @classmethod
 def tearDownClass(cls):cls.browser.close();cls.pw.stop()
 def setUp(self):
  self.context=self.browser.new_context(viewport={'width':1920,'height':1080},device_scale_factor=1);self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)));self.page.set_default_timeout(6000)
  if INLINE:mount(self.page)
  else:
   self.temp=tempfile.TemporaryDirectory();self.server=Server(('127.0.0.1',0),Handler,Library(Path(self.temp.name)));self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.page.goto(f'http://127.0.0.1:{self.server.server_port}');self.page.wait_for_selector('#nav-home')
 def tearDown(self):
  self.context.close()
  if not INLINE:self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()
  self.assertEqual(self.errors,[])
 def state(self):return self.page.evaluate('window.__verify?__verify.getState():import("/src/store.js").then(m=>m.state)')
 def key(self,k):self.page.keyboard.press(k);self.page.wait_for_timeout(70)
 def focus(self):return self.page.evaluate('document.activeElement.id')
 def open_video(self,id='v-coffee'):
  self.page.click('#nav-videos');self.page.click('#card-'+id);self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#media-element").readyState>=2');self.page.wait_for_timeout(160)
 def open_photo(self,id='p-coffee'):
  self.page.click('#nav-photos');self.page.click('#card-'+id);self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#photo-image").naturalWidth>0');self.page.wait_for_timeout(50)
 def settings(self,tab):self.page.click('#nav-settings');self.page.click('#settings-tab-'+tab)
 def pause(self):
  self.page.evaluate('document.querySelector("#media-element").pause()');self.page.wait_for_timeout(100)
 def test_01_boot_real_catalog_no_lab(self):
  self.assertEqual(self.focus(),'hero-play');self.assertNotIn('Evaluation',self.page.locator('body').inner_text());self.assertEqual(self.page.evaluate('typeof window.auraTest'),'undefined');self.page.click('#nav-videos');self.assertEqual(self.page.locator('[data-action="detail"]').count(),3)
 def test_02_header_and_rows_do_not_wrap(self):
  self.key('ArrowRight');self.assertEqual(self.focus(),'hero-explore');self.key('ArrowRight');self.assertEqual(self.focus(),'hero-explore');self.key('ArrowDown');self.assertTrue(self.focus().startswith('collection-'));self.key('ArrowUp');self.assertEqual(self.focus(),'hero-explore')
 def test_03_grid_columns(self):
  self.page.click('#nav-photos');self.page.locator('[data-action="detail"]').nth(1).focus();a=self.focus();self.key('ArrowDown');self.assertNotEqual(self.focus(),a);self.key('ArrowUp');self.assertEqual(self.focus(),a)
 def test_04_modal_trap_and_restore(self):
  self.page.click('#nav-photos');self.page.click('#card-p-coffee');self.key('ArrowRight');self.assertEqual(self.focus(),'detail-save');self.key('Tab');self.assertTrue(self.page.evaluate('document.activeElement.closest("[data-modal-scope]")!==null'));self.key('Escape');self.assertEqual(self.focus(),'card-p-coffee')
 def test_05_settings_category_row_memory(self):
  self.settings('picture');self.page.focus('#settings-tab-picture');self.key('ArrowRight');self.assertEqual(self.focus(),'setting-pictureMode');self.key('ArrowDown');self.assertEqual(self.focus(),'setting-brightness');self.key('ArrowLeft');self.key('ArrowRight');self.assertEqual(self.focus(),'setting-brightness')
 def test_06_slider_immediate_and_exact_return(self):
  self.settings('picture');self.page.click('#setting-brightness');self.assertEqual(self.focus(),'adjust-range');self.key('ArrowRight');self.assertEqual(self.state()['settings']['brightness'],105);self.assertIn('brightness(1.05)',self.page.evaluate('document.documentElement.style.getPropertyValue("--picture")'));self.key('Escape');self.assertEqual(self.focus(),'setting-brightness')
 def test_07_choice_cancel_does_not_apply(self):
  self.settings('appearance');self.page.click('#setting-accent');self.key('ArrowDown');self.key('Escape');self.assertEqual(self.state()['settings']['accent'],'amber');self.assertEqual(self.focus(),'setting-accent')
 def test_08_choice_applies(self):
  self.settings('appearance');self.page.click('#setting-accent');self.page.click('#choice-mint');self.assertEqual(self.state()['settings']['accent'],'mint');self.assertEqual(self.focus(),'setting-accent')
 def test_09_search_typing_keyboard(self):
  self.page.click('#nav-search');self.page.fill('#search-input','coffee');self.assertGreater(self.page.locator('#search-results [data-action="detail"]').count(),0);self.key('Enter');self.assertEqual(self.focus(),'key-A');self.key('ArrowRight');self.assertEqual(self.focus(),'key-B');self.page.click('#key-clear');self.page.click('#key-M');self.assertEqual(self.page.locator('#search-input').input_value(),'M')
 def test_10_search_untrusted_text(self):
  self.page.click('#nav-search');self.page.fill('#search-input','<img src=x onerror=alert(1)>');self.assertEqual(self.page.locator('#search-results img').count(),0);self.assertIn('<img',self.page.locator('#search-results').inner_text())
 def test_11_video_plays_with_native_sound(self):
  self.open_video();wait_for(self.page,'document.querySelector("#media-element").currentTime>.5');actual=self.page.evaluate('({t:document.querySelector("#media-element").currentTime,d:document.querySelector("#media-element").duration,m:document.querySelector("#media-element").muted,v:document.querySelector("#media-element").volume})');self.assertGreater(actual['d'],19);self.assertFalse(actual['m']);self.assertEqual(actual['v'],.65);self.assertIn('Direct',self.page.locator('#player-audio-status').inner_text())
 def test_12_space_pause_and_seek(self):
  self.open_video();self.key('Space');self.assertTrue(self.page.locator('#media-element').evaluate('(e)=>e.paused'));self.page.click('#player-forward');self.assertGreater(self.page.locator('#media-element').evaluate('(e)=>e.currentTime'),9);self.page.click('#player-rewind');self.assertLess(self.page.locator('#media-element').evaluate('(e)=>e.currentTime'),3)
 def test_13_real_volume_and_mute(self):
  self.open_video();self.key('m');self.assertTrue(self.page.locator('#media-element').evaluate('(e)=>e.muted'));self.key('+');self.assertFalse(self.page.locator('#media-element').evaluate('(e)=>e.muted'));self.assertEqual(self.page.locator('#media-element').evaluate('(e)=>e.volume'),.7)
 def test_14_player_volume_dialog_does_not_destroy_media(self):
  self.open_video();self.pause();self.page.evaluate('window.originalElement=document.querySelector("#media-element")');self.page.click('#player-volume');self.key('ArrowLeft');self.key('Escape');self.assertTrue(self.page.evaluate('window.originalElement===document.querySelector("#media-element")'));self.assertEqual(self.focus(),'player-volume');self.assertEqual(self.page.locator('#media-element').evaluate('(e)=>e.volume'),.6)
 def test_15_subtitle_file_and_text(self):
  self.open_video();self.pause();self.page.click('#player-subs');self.page.set_input_files('#subtitle-file',{'name':'captions.srt','mimeType':'text/plain','buffer':b'1\n00:00:01,000 --> 00:00:15,000\n<b>Hello from your own file</b>'});wait_for(self.page,'document.querySelector("#subtitle-message").textContent.includes("loaded")');self.page.click('#subtitle-done');self.page.locator('#media-element').evaluate('(e)=>e.currentTime=2');wait_for(self.page,'document.querySelector("#captions").textContent.includes("Hello")');self.assertEqual(self.page.locator('#captions b').count(),0)
 def test_16_invalid_subtitle_feedback(self):
  self.open_video();self.page.click('#player-subs');self.page.set_input_files('#subtitle-file',{'name':'bad.srt','mimeType':'text/plain','buffer':b'No timed captions'});wait_for(self.page,'document.querySelector("#subtitle-message").textContent.includes("No valid")')
 def test_17_distinct_video_sources_and_next(self):
  self.open_video();first=self.page.locator('#media-element').get_attribute('src');self.page.click('#player-next');wait_for(self.page,'document.querySelector("#media-element").readyState>=2');self.assertNotEqual(first,self.page.locator('#media-element').get_attribute('src'));self.assertEqual(self.page.locator('#player-title').inner_text(),'Into the deep field')
 def test_18_resume_restores_real_position(self):
  self.open_video();self.pause();self.page.locator('#media-element').evaluate('(e)=>e.currentTime=8');self.page.wait_for_timeout(100);self.key('Escape');self.assertEqual(self.focus(),'detail-play');self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#media-element").currentTime>=8');self.key('Space');self.key('Escape');self.key('Escape');self.assertEqual(self.focus(),'card-v-coffee')
 def test_19_speed_changes_native_rate(self):
  self.open_video();self.page.click('#player-speed');self.assertEqual(self.page.locator('#media-element').evaluate('(e)=>e.playbackRate'),1.25)
 def test_20_photo_opens_actual_dimensions(self):
  self.open_photo();self.assertEqual(self.page.locator('#photo-image').evaluate('(e)=>[e.naturalWidth,e.naturalHeight]'),[600,400]);self.assertEqual(self.focus(),'photo-stage')
 def test_21_photo_next_rotate_zoom_back(self):
  self.open_photo();old=self.page.locator('#photo-title').inner_text();self.key('ArrowRight');self.assertNotEqual(self.page.locator('#photo-title').inner_text(),old);self.page.click('#photo-rotate');self.assertIn('90deg',self.page.locator('#photo-image').get_attribute('style'));self.page.click('#photo-zoom');self.assertEqual(self.focus(),'photo-stage');self.assertEqual(self.page.locator('#photo-zoom-label').inner_text(),'1.5×');self.key('Escape');self.assertEqual(self.page.locator('#photo-zoom-label').inner_text(),'Zoom');self.key('Escape');self.assertEqual(self.focus(),'detail-play')
 def test_22_slideshow_advances_and_pause(self):
  self.settings('photos');self.page.click('#setting-photoInterval');self.page.click('#choice-3');self.key('Escape');self.open_photo();self.page.click('#photo-play');old=self.page.locator('#photo-title').inner_text();wait_for(self.page,'(old)=>document.querySelector("#photo-title").textContent!==old',arg=old,timeout=5000);self.key('Space');self.assertEqual(self.page.locator('#photo-play').get_attribute('aria-pressed'),'false')
 def test_23_photo_information_return(self):
  self.open_photo();src=self.page.locator('#photo-image').get_attribute('src');self.page.click('#photo-info');self.assertIn('600',self.page.locator('#overlay').inner_text());self.key('Escape');self.assertEqual(self.page.locator('#photo-image').get_attribute('src'),src);self.assertEqual(self.focus(),'photo-info')
 def test_24_favorites_and_profiles(self):
  self.page.click('#nav-videos');self.page.click('#card-v-coffee');self.page.click('#detail-save');self.key('Escape');self.page.click('#nav-saved');self.assertEqual(self.page.locator('[data-action="detail"]').count(),1);self.page.click('#nav-profile');self.page.click('#profile-guest');self.page.click('#nav-saved');self.assertEqual(self.page.locator('[data-action="detail"]').count(),0)
 def test_25_hide_included_collection(self):
  self.settings('library');self.page.click('#setting-showSamples');self.key('Escape');self.page.click('#nav-videos');self.assertEqual(self.page.locator('[data-action="detail"]').count(),0);self.assertIn('Nothing here',self.page.locator('#view').inner_text())
 def test_26_import_dialog_remote_and_close(self):
  self.page.click('#nav-add');self.assertEqual(self.focus(),'choose-files');self.key('ArrowDown');self.assertEqual(self.focus(),'choose-folder');self.key('ArrowDown');self.assertEqual(self.focus(),'add-link');self.key('Escape');self.assertEqual(self.focus(),'nav-add')
 def test_27_unsafe_link_rejected(self):
  self.page.click('#nav-add');self.page.click('#add-link');self.page.fill('#media-url','javascript:alert(1)');self.page.click('#link-submit');self.assertIn('HTTP',self.page.locator('#link-error').inner_text());self.assertEqual(self.state()['links'],[])
 def test_28_link_added_and_removed(self):
  self.page.click('#nav-add');self.page.click('#add-link');self.page.fill('#media-url','https://example.com/myvideo.mp4');self.page.fill('#link-name','My video');self.page.click('#link-submit');self.page.wait_for_selector('#detail-title');self.assertEqual(self.page.locator('#detail-title').inner_text(),'My video');self.assertEqual(self.state()['links'][0]['url'],'https://example.com/myvideo.mp4');self.page.click('#detail-manage');self.page.click('#option-0');self.page.click('#confirm-ok');wait_for(self.page,'document.querySelector("#detail-title")===null');self.assertEqual(self.state()['links'],[])
 def test_29_standby_wake_and_focus(self):
  self.settings('system');self.page.click('#system-standby');self.assertTrue(self.page.locator('.standby').is_visible());self.key('Enter');self.assertEqual(self.page.locator('.standby').count(),0)
 def test_30_reset_confirmation_canceled(self):
  self.settings('privacy');before=self.state();self.page.click('#system-reset');self.assertEqual(self.focus(),'confirm-cancel');self.key('Enter');self.assertEqual(self.state(),before)
 def test_31_invalid_import_atomic(self):
  self.settings('privacy');before=self.state();self.page.click('#system-import');self.page.set_input_files('#backup-file',{'name':'bad.json','mimeType':'application/json','buffer':b'{"version":3,"settings":{"volume":900}}'});wait_for(self.page,'document.querySelector("#restore-message").textContent.includes("Not restored")');self.assertEqual(self.state(),before)
 def test_32_audio_track_is_real_media(self):
  self.page.click('#nav-music');self.page.locator('[data-action="detail"]').first.click();self.page.click('#detail-play');wait_for(self.page,'document.querySelector("audio#media-element").currentTime>.2');self.assertTrue(self.page.locator('.music-stage').is_visible());self.assertTrue(self.page.locator('#player-subs').is_hidden())
 def test_33_all_settings_pages_fit_and_focus(self):
  self.page.click('#nav-settings')
  for tab in ['picture','sound','appearance','access','playback','photos','library','profiles','system','privacy']:
   self.page.click('#settings-tab-'+tab);self.assertTrue(self.page.locator('#settings-panel').is_visible());self.assertTrue(self.focus().startswith(('setting-','settings-','system-','library-')) or self.focus()=='sound-sample',self.focus());self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),1921)
 def test_34_responsive_boundaries(self):
  for w,h in [(1280,720),(1920,1080),(3840,2160),(800,600)]:
   self.page.set_viewport_size({'width':w,'height':h});self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),w+1);self.assertTrue(self.page.locator('#nav-settings').is_visible())
 @unittest.skipIf(INLINE,'Requires a real browser origin; not mocked Storage.')
 def test_35_native_reload_persistence(self):
  self.settings('picture');self.page.click('#setting-brightness');self.key('ArrowRight');self.key('Escape');self.page.reload();self.page.wait_for_selector('#nav-home');self.assertEqual(self.state()['settings']['brightness'],105)
 @unittest.skipIf(INLINE,'Requires real browser HTTP upload transport.')
 def test_36_native_upload_video_photo_and_restart(self):
  self.page.click('#nav-add');self.page.set_input_files('#media-files',[str(ROOT/'assets/photos/coffee.jpg'),str(ROOT/'assets/media/liftoff.webm')]);wait_for(self.page,'document.querySelector("#import-status").textContent.startsWith("2 items added")',timeout=25000);self.page.click('#import-done');self.page.reload();self.page.wait_for_selector('#nav-videos');self.page.click('#nav-videos');self.page.click('#source-import');self.assertEqual(self.page.locator('[data-action="detail"]').count(),1);self.page.locator('[data-action="detail"]').first.click();self.page.click('#detail-play');wait_for(self.page,'document.querySelector("#media-element").currentTime>.5')
 def test_37_autoplay_preference_off_requires_play(self):
  self.settings('playback');self.page.click('#setting-autoplay');self.key('Escape');self.open_video();self.assertTrue(self.page.locator('#media-element').evaluate('(e)=>e.paused'));self.key('Enter');wait_for(self.page,'document.querySelector("#media-element").currentTime>.2')
 def test_38_valid_backup_restores_settings(self):
  backup=self.state();backup['settings']['volume']=85;self.settings('privacy');self.page.click('#system-import');self.page.set_input_files('#backup-file',{'name':'good.json','mimeType':'application/json','buffer':json.dumps(backup).encode()});wait_for(self.page,'document.querySelector("#restore-title")===null');self.assertEqual(self.state()['settings']['volume'],85)
if __name__=='__main__':unittest.main(verbosity=2)
