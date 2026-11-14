"""Capture the actual UI in the documented developer-only inline harness."""
import os
from playwright.sync_api import sync_playwright
from browser_support import wait_for
from harness import mount,ROOT
screens=ROOT/'screenshots';screens.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=os.environ.get('BROWSER_EXECUTABLE') or None,headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1920,'height':1080},device_scale_factor=1)
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)));mount(page)
 def shot(name):
  page.evaluate('Promise.all([...document.images].map(i=>i.decode().catch(()=>{})))');page.wait_for_timeout(180);page.screenshot(path=str(screens/(name+'.png')))
 shot('home');page.click('#nav-photos');shot('photos')
 page.click('#card-p-deep-field');page.click('#detail-play');shot('photo-viewer');page.keyboard.press('Escape');page.keyboard.press('Escape')
 page.click('#nav-add');shot('add-media');page.keyboard.press('Escape');page.click('#nav-settings');shot('settings-picture')
 page.click('#settings-tab-sound');shot('settings-sound');page.click('#setting-audioPath');shot('sound-path');page.keyboard.press('Escape')
 page.click('#settings-tab-photos');shot('settings-photos');page.click('#settings-tab-picture');page.click('#setting-brightness');shot('brightness');page.keyboard.press('Escape');page.keyboard.press('Escape');page.keyboard.press('Escape')
 page.click('#nav-search');page.fill('#search-input','');shot('search');page.click('#nav-videos');page.click('#card-v-deep-field');shot('detail');page.click('#detail-play');wait_for(page,'document.querySelector("#media-element").currentTime>.6');page.evaluate('document.querySelector("#media-element").pause()');page.wait_for_timeout(150);shot('player');page.keyboard.press('Escape');page.keyboard.press('Escape')
 page.click('#nav-music');page.click('#card-a-coffee');page.click('#detail-play');wait_for(page,'document.querySelector("#media-element").currentTime>.6');page.evaluate('document.querySelector("#media-element").pause()');shot('music-player')
 for w,h in [(1280,720),(3840,2160)]:
  page.keyboard.press('Escape');page.keyboard.press('Escape');page.set_viewport_size({'width':w,'height':h});page.click('#nav-settings');page.click('#settings-tab-photos');shot(f'settings-{w}');page.keyboard.press('Escape')
 print('Screenshots captured; page errors:',errors);assert not errors;b.close()
