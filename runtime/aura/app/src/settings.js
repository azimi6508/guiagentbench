import {state,currentProfile,profileData,storageAvailable} from './store.js';
import {DEFAULT_SETTINGS,SCHEMA,RANGES,VERSION,PROFILES,art} from './data.js';
import {icon} from './icons.js';

export const SETTINGS = [
 {id:'picture',title:'Picture',icon:'display',eyebrow:'A MORE CINEMATIC VIEW',description:'Fine-tune the picture. Keep every detail.',groups:[
  ['Picture preferences',[
   ['pictureMode','Picture mode','Start with a balanced picture, a restrained cinema look, or richer color.'],
   ['brightness','Brightness','Lift shadows or soften a bright scene. Applies to artwork and video, not your display hardware.'],
   ['contrast','Contrast','Adjust the separation between light and dark.'],
   ['saturation','Color intensity','Find your ideal color balance. At 0%, artwork and video become monochrome.'],
   ['temperature','Color temperature','Add a warm or cool tint to artwork and video.']]],
  ['Video framing', [['videoFit','Picture size','Original preserves the full frame. Fill crops the picture to cover the playback window.']]]
 ]},
 {id:'sound',title:'Sound',icon:'volume',eyebrow:'SOUND, BEAUTIFULLY BALANCED',description:'From quiet evenings to bigger moments.',groups:[
  ['Volume & character',[
   ['volume','Volume','Set the volume for all sound inside AURA. Your computer or TV volume stays unchanged.'],
   ['muted','Mute','Silence playback, sound samples, and remote feedback.'],
   ['audioPath','Audio processing','Direct uses the browser’s native audio for maximum compatibility. Enhanced enables the sound controls below for local media.'],
   ['soundMode','Sound mode','Equalization and dynamics for Enhanced audio. Direct playback keeps the original soundtrack.'],
   ['bass','Bass','Enhanced audio only: boost or reduce low frequencies, on top of the selected sound mode.'],
   ['treble','Treble','Enhanced audio only: adjust high-frequency detail, on top of the selected sound mode.'],
   ['balance','Left / right balance','Enhanced audio only: move sound toward the left or right output channel.'],
   ['monoAudio','Mono audio','Enhanced audio only: combine both channels so the complete mix reaches either speaker. Balance is applied afterward.']]],
  ['Remote feedback',[
   ['navSounds','Navigation sounds','Hear a subtle click when moving between controls.'],
   ['navVolume','Navigation volume','Set the level of navigation feedback relative to the main volume.']]]
 ]},
 {id:'appearance',title:'Appearance',icon:'spark',eyebrow:'MAKE YOURSELF AT HOME',description:'A space that feels like yours.',groups:[
  ['Interface',[
   ['theme','Background','Choose a deep blue, a softer slate, or a near-black background.'],
   ['accent','Accent color','Personalize selected controls, focus indicators, and playback progress.'],
   ['focusStyle','Focus highlight','Choose a soft halo or a clean outline for remote navigation.']]],
  ['Clock',[
   ['showClock','Show clock','Keep the current time visible in the top navigation.'],
   ['clock24','24-hour time','Use a 24-hour clock in the interface.']]]
 ]},
 {id:'access',title:'Accessibility',icon:'access',eyebrow:'COMFORT IN EVERY DETAIL',description:'Clearer text. Calmer movement. Your pace.',groups:[
  ['Captions',[
   ['captions','Show subtitles','Display the subtitle file opened for the current video. Add SRT or WebVTT subtitles from the player.'],
   
   ['captionSize','Caption size','Make captions easier to read from your seat.'],
   ['captionBackground','Caption background','Choose a translucent panel, solid black, or text with a shadow.']]],
  ['Visibility & motion',[
   ['largeText','Larger text','Increase card labels, settings text, and reading sizes.'],
   ['highContrast','High contrast','Use brighter secondary text and more distinct control boundaries.'],
   ['reducedMotion','Reduce motion','Turn off interface animation and focus scaling. Video playback is not changed.']]]
 ]},
 {id:'playback',title:'Playback',icon:'play',eyebrow:'LESS FRICTION, MORE STORY',description:'Pick up exactly where you want to.',groups:[
  ['Playback preferences',[
   ['autoplay','Start playback on open','Begin the selected video or music track when you choose Play. When off, press Play once the player opens.'],
   ['resume','Resume where you left off','Continue from the last stored position for your current profile.'],
   ['playbackRate','Playback speed','Change the speed of the selected video and its soundtrack, or the current music track.'],
   ['controlsTimeout','Hide player controls','Hide controls after a period of inactivity while playing. Any arrow reveals them without activating anything.'],
   ['playNext','Play next automatically','Continue to the next item in the current video or music collection.'],
   ['repeatMode','Repeat playback','Repeat one item, repeat the collection, or stop at the end.']]],
  ['On launch', [['startupPage','Start screen','Choose the page AURA opens on your next visit.']]]
 ]},
 {id:'photos',title:'Photos',icon:'image',eyebrow:'A BIGGER VIEW OF YOUR WORLD',description:'Let the small moments fill the screen.',groups:[
  ['Photo viewer',[
   ['photoFit','Photo framing','Fit keeps the entire photo visible. Fill crops the image to the screen.'],
   ['photoInterval','Slideshow interval','Choose how long each photograph stays on screen.'],
   ['photoRepeat','Repeat slideshow','Return to the first photo at the end of the collection.']]]
 ]},
 {id:'library',title:'Media library',icon:'folder',eyebrow:'ALL YOUR FAVORITES, TOGETHER',description:'Keep your collection feeling like home.',groups:[
  ['Browsing preferences',[
   ['showSamples','Show AURA collection','Show or hide the included photographic motion studies, photographs, and original music. Your own media stays visible.'],
   ['sortOrder','Default sort order','Arrange media by recently added, title, or duration.'],
   ['thumbnailSize','Card density','Choose spacious cards or fit more media on the screen.']]]
 ]},
 {id:'profiles',title:'Profiles',icon:'user',eyebrow:'A PLACE FOR EVERYONE',description:'Separate favorites and playback history. The media library is shared.',groups:[]},
 {id:'system',title:'System',icon:'settings',eyebrow:'READY WHEN YOU ARE',description:'A few thoughtful everyday essentials.',groups:[
  ['Power & standby',[
   ['sleepMinutes','Sleep timer','Enter AURA standby after this interval. The timer starts when selected and resets to Off afterward.'],
   ['idleMinutes','Standby when idle','Enter standby after no remote or pointer activity. Playing video, music, a slideshow, or importing files keeps AURA awake.']]]
 ]},
 {id:'privacy',title:'Storage & privacy',icon:'heart',eyebrow:'YOUR SPACE, YOUR CONTROL',description:'Your preferences stay in this browser.',groups:[
  ['Personal data',[
   ['rememberHistory','Remember watch history','Save new playback positions for your profile. Turning this off does not delete your existing history.']]]
 ]}
];
export const LABELS={
 standard:'Standard',cinema:'Cinema',vivid:'Vivid',neutral:'Neutral',warm:'Warm',cool:'Cool',
 contain:'Original',cover:'Fill screen',lavender:'Iris',mint:'Sage',amber:'Amber',blue:'Sky',
 midnight:'Midnight',slate:'Slate',oled:'Deep black',small:'Small',medium:'Medium',large:'Large',
 en:'English',tr:'Türkçe',dark:'Translucent',solid:'Solid black',clear:'Text only',
 halo:'Soft halo',outline:'Clean outline',dialogue:'Clear voice',night:'Night',
 home:'Home',videos:'Videos',photos:'Photos',music:'Music',saved:'Saved',direct:'Direct · recommended',enhanced:'Enhanced · local media',off:'Off',one:'Repeat one',all:'Repeat collection',added:'Recently added',title:'Title A–Z',duration:'Longest first',comfortable:'Comfortable',compact:'Compact'
};
export function definition(key){
 for(const category of SETTINGS)for(const [,rows] of category.groups){const row=rows.find(x=>x[0]===key);if(row)return {key,label:row[1],description:row[2],category:category.id};}
 return null;
}
export function valueLabel(key,v=state.settings[key]) {
 if(typeof v==='boolean')return v?'On':'Off';
 if(['brightness','contrast','saturation','volume','navVolume'].includes(key))return `${v}%`;
 if(['bass','treble'].includes(key))return (v>0?'+':'')+v+' dB';
 if(key==='balance')return v===0?'Center':`${v<0?'Left':'Right'} ${Math.abs(v)}%`;
 if(key==='sleepMinutes'||key==='idleMinutes')return v?`${v} minutes`:'Off';
 if(key==='photoInterval')return `${v} seconds`;
 if(key==='controlsTimeout')return v?`${v} seconds`:'Always visible';
 if(key==='playbackRate')return v===1?'Normal':`${v}×`;
 if(key==='photoFit')return v==='contain'?'Fit to screen':'Fill screen';
 return LABELS[v]||String(v);
}
function rowInner(key) {
 const def=definition(key),v=state.settings[key],bool=SCHEMA[key]==='boolean';
 return `<span class="setting-text"><strong id="setting-label-${key}">${def.label}</strong><span id="setting-description-${key}">${rowSubtitle(key)}</span></span><span class="setting-trailing">${bool?`<span class="switch-label" aria-hidden="true">${v?'On':'Off'}</span><span class="tv-switch ${v?'on':''}" aria-hidden="true"><i></i></span>`:`<span id="setting-value-${key}" class="setting-value">${valueLabel(key)}</span>${icon('right','sm')}`}</span>`;
}
function rowSubtitle(key){
 if(['soundMode','bass','treble','balance','monoAudio'].includes(key)&&state.settings.audioPath==='direct')return 'Used with Enhanced audio';
 if(key==='audioPath')return state.settings.audioPath==='direct'?'Original sound · best compatibility':'Equalizer, balance & mono for local files';
 if(key==='volume'&&state.settings.muted)return 'Audio muted · unmute to hear changes';
 if(key==='navVolume'&&!state.settings.navSounds)return 'Navigation sounds are off';
 if(key==='clock24'&&!state.settings.showClock)return 'Clock is currently hidden';
 const text={pictureMode:'Color, contrast & brightness',brightness:'Shadows & highlights',contrast:'Light & dark detail',saturation:'From monochrome to vivid',temperature:'Warm, neutral, or cool',videoFit:'Preserve the frame or fill the screen',volume:'All AURA audio',muted:'Playback & interface sounds',soundMode:'Equalization & dynamics',bass:'Low-frequency adjustment',treble:'High-frequency adjustment',balance:'Stereo position',monoAudio:'Combine left and right',navSounds:'A soft click with every move',navVolume:'Relative to main volume',theme:'Set the mood',accent:'Focus & active controls',focusStyle:'Make your selection unmistakable',showClock:'Time at a glance',clock24:'Clock format',captions:'Use the subtitles opened in the player',captionSize:'Comfortable reading at a distance',captionBackground:'Improve contrast over video',largeText:'Settings & content labels',highContrast:'Text, boundaries & focus',reducedMotion:'A calmer interface',autoplay:'When opening a title',resume:'Your profile’s last position',playbackRate:'Video & audio speed',controlsTimeout:'Only while playing',playNext:'Continue through your collection',repeatMode:'One item or the whole collection',startupPage:'Applied on the next launch',photoFit:'The whole photo or an edge-to-edge view',photoInterval:'Time between photographs',photoRepeat:'Start again after the final photo',showSamples:'Included videos, photographs & music',sortOrder:'How your collection is arranged',thumbnailSize:'Spacious cards or more on screen',sleepMinutes:'One-time countdown',idleMinutes:'When playback and activity stop',rememberHistory:'New playback positions'};
 return text[key]||'';
}
function settingButton(key){
 const bool=SCHEMA[key]==='boolean';
 return `<button id="setting-${key}" class="setting-item" data-focus data-action="open-setting" data-setting="${key}" aria-labelledby="setting-label-${key}${bool?'':` setting-value-${key}`}" aria-describedby="setting-description-${key}" ${bool?`role="switch" aria-checked="${state.settings[key]}"`: 'aria-haspopup="dialog"'}>${rowInner(key)}</button>`;
}
function actionRow(id,action,label,sub,ico='right',extra=''){
 return `<button id="${id}" class="setting-item action-item" data-focus data-action="${action}" ${extra}><span class="setting-text"><strong>${label}</strong><span>${sub}</span></span>${icon(ico)}</button>`;
}
export function categoryRows(tab){
 const cat=SETTINGS.find(c=>c.id===tab)||SETTINGS[0];
 let html='';
 if(tab==='profiles')html+=`<h3 class="group-label">Who’s watching</h3>${PROFILES.map(p=>`<button data-focus id="settings-profile-${p.id}" data-action="switch-profile" data-profile="${p.id}" class="setting-item profile-setting" aria-pressed="${state.profile===p.id}"><span class="avatar" style="--profile-color:${p.color}">${p.initial}</span><span class="setting-text"><strong>${p.name}</strong><span>${'Your own collection & history'}</span></span>${state.profile===p.id?icon('check'):icon('right','sm')}</button>`).join('')}`;
 for(const [heading,rows]of cat.groups)html+=`<h3 class="group-label">${heading}</h3><div class="setting-group">${rows.map(([key])=>settingButton(key)).join('')}</div>`;
 if(tab==='library')html+=`<h3 class="group-label">Your sources</h3>${actionRow('library-import','add-media','Import media','Add videos, photographs, or music from your device','plus')}${actionRow('library-rescan','rescan','Refresh connected folders','Look for new or changed files in your read-only folders','reset')}`;
 if(tab==='sound')html+=`<h3 class="group-label">Listen</h3>${actionRow('sound-sample','sound-sample','Play sound sample','A short stereo chime at your current volume','volume')}`;
 if(tab==='system')html+=`<h3 class="group-label">Display & device</h3>${actionRow('system-fullscreen','fullscreen',document.fullscreenElement?'Exit fullscreen':'Enter fullscreen','Use the entire browser display','fullscreen')}${actionRow('system-standby','standby','Standby now','Pause AURA until you return','power')}${actionRow('system-about','about','About AURA TV',`Version ${VERSION}`,'info')}`;
 if(tab==='privacy')html+=`<h3 class="group-label">${currentProfile().name}’s collection</h3>${actionRow('system-clear-history','clear-history','Clear watch history',`${Object.keys(profileData().history).length} saved playback positions`,'reset')}${actionRow('system-clear-saved','clear-saved','Clear watchlist',`${profileData().watchlist.length} saved titles`,'heart')}<h3 class="group-label">Backup & restore</h3>${actionRow('system-export','export','Back up preferences','Preferences, favorites, history & media links','download')}${actionRow('system-import','import','Restore a backup','Choose an AURA backup file; media files stay in place','upload')}${actionRow('system-reset','factory-reset','Reset AURA TV','Restore defaults in this browser only','reset')}`;
 if(!['profiles','system','privacy'].includes(tab))html+=`<h3 class="group-label">Reset</h3>${actionRow('category-reset','reset-category',`Reset ${cat.title.toLowerCase()}`,'Restore defaults for this category only','reset')}`;
 return html;
}
export function settingsPanel(tab){
 const cat=SETTINGS.find(c=>c.id===tab)||SETTINGS[0];
 return `<div class="settings-section-heading"><span>${cat.eyebrow}</span><h2>${cat.title}</h2><p>${cat.description}</p></div><div id="settings-rows" data-zone="settings-rows-${tab}" data-layout="vertical" class="settings-rows">${categoryRows(tab)}</div>`;
}
export function settingsPage(tab){
 return `<div class="tv-settings"><div class="settings-titlebar" data-zone="settings-top" data-layout="horizontal"><button id="settings-back" data-focus data-action="back" class="settings-back">${icon('back')}<span>Settings</span></button><div id="settings-save-status" class="saved-label" role="status" aria-live="polite" aria-atomic="true">${icon(storageAvailable?'check':'info','sm')}${storageAvailable?'Saved on this device':'Session only · storage unavailable'}</div></div><div class="settings-workspace"><aside class="settings-categories" data-zone="settings-categories" data-layout="vertical" aria-label="Settings categories">${SETTINGS.map(cat=>`<button id="settings-tab-${cat.id}" data-focus data-action="settings-tab" data-tab="${cat.id}" class="category ${tab===cat.id?'selected':''}" ${tab===cat.id?'aria-current="page"':''}>${icon(cat.icon)}<span>${cat.title}</span><i></i></button>`).join('')}<div class="category-signature"><span class="brand-mark">A</span><span>AURA TV<small>A little more you.</small></span></div></aside><section id="settings-panel" class="settings-panel" aria-label="Settings controls">${settingsPanel(tab)}</section><aside id="settings-context" class="settings-context" aria-label="Setting information">${contextPanel(tab)}</aside></div></div>`;
}
export function contextPanel(tab,key=null) {
 const cat=SETTINGS.find(c=>c.id===tab)||SETTINGS[0],def=definition(key);
 const title=def?.label||cat.title,desc=def?.description||cat.description;
 let visual='';
 if(['picture','appearance'].includes(tab))visual=`<div class="context-picture"><img class="picture" src="${art('p-liftoff')}" alt="Falcon 9 launch photograph"><div class="preview-caption"><span>YOUR PICTURE</span><strong>Every<br>little detail.</strong></div></div><div class="preview-meta"><span>${valueLabel('pictureMode')} picture</span><span>${valueLabel('temperature')}</span></div>`;
 else if(tab==='sound')visual=`<div class="sound-visual"><div class="sound-orbit">${icon(state.settings.muted?'mute':'volume')}</div><div class="sound-bars" aria-hidden="true">${Array.from({length:21},(_,i)=>`<i style="--bar:${Math.sin(i*.8)*.5+.5}"></i>`).join('')}</div><span id="sound-status">${state.settings.muted?'Audio muted':state.settings.volume===0?'Volume is at zero':`${state.settings.volume}% volume · ${state.settings.audioPath==='direct'?'Direct sound':`${valueLabel('soundMode')} · Enhanced`}`}</span></div>`;
 else if(tab==='access')visual=`<div class="caption-preview"><img class="picture" src="${art('p-deep-field')}" alt="Deep-field photograph"><div class="caption-example">A world worth exploring.</div></div><div class="preview-meta"><span>Text appearance preview</span><span>${valueLabel('captionSize')} captions</span></div>`;
 else if(tab==='profiles')visual=`<div class="context-profile"><span class="avatar" style="--profile-color:${currentProfile().color}">${currentProfile().initial}</span><strong>${currentProfile().name}</strong><span>${profileData().watchlist.length} saved titles</span></div>`;
 else visual=`<div class="context-symbol">${icon(cat.icon)}<div class="context-symbol-glow"></div></div>`;
 const hints={picture:'Picture adjustments change AURA artwork and video only.',sound:'Audio follows your browser’s current output device.',appearance:'Your theme is saved automatically.',access:'Every setting is available with your remote.',playback:'Your real files, at your own pace.',profiles:'Each profile has its own watchlist and watch history.',system:'Standby pauses the app. It never powers off your device.',privacy:'No accounts or analytics. Imported files remain on this computer.',photos:'Rotation and zoom never modify your original photographs.',library:'Imports stay in AURA’s data folder. Connected folders are read-only.'};
 return `<div class="context-visual">${visual}</div><div class="context-copy"><span class="context-overline">${def?'ABOUT THIS SETTING':'YOUR EXPERIENCE'}</span><h3>${title}</h3><p>${desc}</p>${def?`<div class="context-current"><span>Current setting</span><strong>${valueLabel(key)}</strong></div>`:''}</div><div class="context-tip">${icon('info','sm')}<span>${hints[tab]}</span></div><div class="context-remote"><kbd>↑ ↓</kbd> Browse &nbsp; <kbd>OK</kbd> Adjust<br><kbd>←</kbd> Categories &nbsp; <kbd>Back</kbd> Return</div>`;
}
export function refreshSetting(key){
 const status=document.getElementById('settings-save-status'),message=storageAvailable?'Saved on this device':'Session only · storage unavailable';
 if(status&&status.textContent!==message)status.innerHTML=icon(storageAvailable?'check':'info','sm')+message;
 const related={audioPath:['soundMode','bass','treble','balance','monoAudio'],muted:['volume'],navSounds:['navVolume'],showClock:['clock24']};
 for(const name of [key,...(related[key]||[])]){
  const el=document.getElementById('setting-'+name);if(!el)continue;
  el.innerHTML=rowInner(name);
  if(SCHEMA[name]==='boolean')el.setAttribute('aria-checked',String(state.settings[name]));
 }
}
export function dialogForSetting(key){
 const def=definition(key),val=state.settings[key];
 if(!def||SCHEMA[key]==='boolean')throw Error('This setting does not use an adjustment dialog.');
 const title=`<div class="setting-dialog-heading"><span class="context-overline">${SETTINGS.find(c=>c.id===def.category).title}</span><h2 id="adjust-title">${def.label}</h2><p id="adjust-description">${def.description}</p></div>`;
 let body,focus;
 if(RANGES[key]){
  const [min,max,step]=RANGES[key];focus='adjust-range';
  const preview=def.category==='picture'?`<div class="adjust-preview"><img class="picture" src="${art('p-liftoff')}" alt="Live picture preview"></div>`:'';
  body=`${preview}<div class="range-dialog-body"><output id="adjust-value" for="adjust-range">${valueLabel(key)}</output><div class="adjust-track" data-zone="adjust-slider" data-layout="horizontal"><span>${min}</span><input data-focus id="adjust-range" type="range" min="${min}" max="${max}" step="${step}" value="${val}" style="--range-progress:${(val-min)/(max-min)*100}%" data-setting="${key}" aria-label="${def.label}" aria-valuetext="${valueLabel(key)}" aria-describedby="adjust-instruction"><span>${max}</span></div><div id="adjust-instruction" class="adjust-instruction"><kbd>← →</kbd> Adjust in steps of ${step}${['bass','treble'].includes(key)?' dB':''}</div></div><div class="setting-dialog-footer" data-zone="adjust-actions" data-layout="horizontal"><span>Changes apply immediately</span><button data-focus id="adjust-done" class="btn primary" data-action="close">Done ${icon('check','sm')}</button></div>`;
 } else {
  focus='choice-'+String(val).replace('.','-');
  const descriptions={direct:'Native playback without a Web Audio dependency',enhanced:'Local media uses equalization, balance and mono processing',standard:'Balanced and natural',cinema:'A richer, cinematic character',vivid:'Brighter highlights and richer color',dialogue:'More presence in the speech range',night:'Softer bass and compressed loud peaks',contain:'Show the complete picture, with bars when needed',cover:'Fill the screen by cropping the picture',halo:'A luminous outline with a soft glow',outline:'A strong, simple border without the glow',midnight:'Deep blue with subtle layered surfaces',slate:'Softer blue-gray surfaces',oled:'Near-black background and darker surfaces'};
  body=`<div class="choice-list" data-zone="choices" data-layout="vertical" data-down="choice-footer">${SCHEMA[key].map(value=>`<button data-focus id="choice-${String(value).replace('.','-')}" class="choice ${val===value?'selected':''}" data-action="choose-setting" data-setting="${key}" data-value="${value}" aria-pressed="${val===value}">${['accent','theme'].includes(key)?`<i class="color-swatch swatch-${value}"></i>`:''}<span><strong>${valueLabel(key,value)}</strong>${descriptions[value]?`<small>${descriptions[value]}</small>`:''}</span>${val===value?icon('check'): '<i class="choice-circle"></i>'}</button>`).join('')}</div><div class="choice-cancel" data-zone="choice-footer" data-layout="horizontal" data-up="choices"><span><kbd>↑ ↓</kbd> Choose &nbsp; <kbd>OK</kbd> Apply</span><button data-focus id="adjust-cancel" data-action="close" class="btn ghost">Cancel</button></div>`;
 }
 return {focus,html:`<div class="modal-backdrop"><section class="setting-dialog" data-modal-scope role="dialog" aria-modal="true" aria-labelledby="adjust-title" aria-describedby="adjust-description">${title}${body}</section></div>`};
}
export function categoryDefaults(tab){
 const category=SETTINGS.find(c=>c.id===tab),patch={};
 if(!category)return patch;
 for(const[,rows]of category.groups)for(const[key]of rows)patch[key]=DEFAULT_SETTINGS[key];
 return patch;
}
