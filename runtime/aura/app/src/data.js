/** Catalog records describe actual bundled files, never fictional movie metadata. */
export const VERSION='3.1.0';
export const BUILTINS=[
 {id:'v-liftoff',title:'Before liftoff',kind:'video',duration:22.008,url:'assets/media/liftoff.webm',poster:'assets/photos/liftoff.jpg',album:'AURA collection',description:'A photographic motion study of Falcon 9, set to an original stereo score. A 22-second pan and zoom, not footage of a launch.',credit:'Photograph: SpaceX · Public domain. Motion and music: AURA · MIT.',width:1280,height:720},
 {id:'v-deep-field',title:'Into the deep field',kind:'video',duration:24.008,url:'assets/media/deep-field.webm',poster:'assets/photos/deep-field.jpg',album:'AURA collection',description:'Drift through a Hubble deep-field photograph. An original ambient score accompanies this 24-second photographic motion study.',credit:'Photograph: NASA / ESA / STScI. Motion and music: AURA · MIT.',width:1280,height:720},
 {id:'v-coffee',title:'A slower morning',kind:'video',duration:20.008,url:'assets/media/coffee.webm',poster:'assets/photos/coffee.jpg',album:'AURA collection',description:'A quiet photographic motion study of a morning coffee, with an original, warmer instrumental score. Duration: 20 seconds.',credit:'Photograph: Rachel Michetti, courtesy of Pikolo Espresso Bar · CC0. Motion and music: AURA · MIT.',width:1280,height:720},
 {id:'p-liftoff',title:'The moment before',kind:'photo',url:'assets/photos/liftoff.jpg',poster:'assets/photos/liftoff.jpg',album:'Beyond the everyday',credit:'SpaceX · Public domain',width:640,height:427},
 {id:'p-deep-field',title:'A universe of possibility',kind:'photo',url:'assets/photos/deep-field.jpg',poster:'assets/photos/deep-field.jpg',album:'Beyond the everyday',credit:'NASA / ESA / STScI · Hubble deep field',width:1000,height:872},
 {id:'p-portrait',title:'A life beyond Earth',kind:'photo',url:'assets/photos/portrait.jpg',poster:'assets/photos/portrait.jpg',album:'Beyond the everyday',credit:'NASA · Eileen Collins portrait · Public domain',width:512,height:512},
 {id:'p-coffee',title:'Morning ritual',kind:'photo',url:'assets/photos/coffee.jpg',poster:'assets/photos/coffee.jpg',album:'Everyday stories',credit:'Rachel Michetti / Pikolo Espresso Bar · CC0',width:600,height:400},
 {id:'p-chelsea',title:'In good company',kind:'photo',url:'assets/photos/chelsea.jpg',poster:'assets/photos/chelsea.jpg',album:'Everyday stories',credit:'Stefan van der Walt · CC0',width:451,height:300},
 {id:'a-deep-field',title:'Weightless',kind:'audio',url:'assets/media/deep-field.ogg',poster:'assets/photos/deep-field.jpg',duration:24.006,album:'Small moments',credit:'Original AURA instrumental · MIT',description:'A short original ambient instrumental. Stereo · 24 seconds.'},
 {id:'a-liftoff',title:'Departure',kind:'audio',url:'assets/media/liftoff.ogg',poster:'assets/photos/liftoff.jpg',duration:22.006,album:'Small moments',credit:'Original AURA instrumental · MIT',description:'A short original instrumental with a rising melody. Stereo · 22 seconds.'},
 {id:'a-coffee',title:'Sunday, slowly',kind:'audio',url:'assets/media/coffee.ogg',poster:'assets/photos/coffee.jpg',duration:20.006,album:'Small moments',credit:'Original AURA instrumental · MIT',description:'A warm, short original instrumental. Stereo · 20 seconds.'}
].map((m,i)=>({...m,sources:m.kind==='video'?[{url:m.url,type:'video/webm; codecs=\"vp9,opus\"'},{url:m.url.replace(/\.webm$/,'.mp4'),type:'video/mp4'}]:m.kind==='audio'?[{url:m.url,type:'audio/ogg; codecs=\"opus\"'},{url:m.url.replace(/\.ogg$/,'.mp3'),type:'audio/mpeg'}]:undefined,source:'included',added:1700000000+i,mime:m.kind==='video'?'video/webm':m.kind==='audio'?'audio/ogg':'image/jpeg',name:m.url.split('/').at(-1)}));
export let CATALOG=[...BUILTINS];
export function replaceCatalog(items){CATALOG=[...items,...BUILTINS];}
export const byId=id=>CATALOG.find(x=>x.id===id);
export const art=id=>byId(id)?.poster || 'assets/photos/liftoff.jpg';
export const PROFILES=[{id:'alex',name:'Alex',initial:'A',color:'#c7caff'},{id:'guest',name:'Guest',initial:'G',color:'#9ed9c4'},{id:'kids',name:'Family',initial:'F',color:'#edc594'}];
export const DEFAULT_SETTINGS={
 pictureMode:'standard',brightness:100,contrast:100,saturation:100,temperature:'neutral',videoFit:'contain',
 accent:'amber',theme:'oled',volume:65,muted:false,navSounds:true,navVolume:20,
 audioPath:'direct',soundMode:'standard',bass:0,treble:0,balance:0,monoAudio:false,
 captions:true,captionSize:'medium',captionBackground:'dark',
 highContrast:false,reducedMotion:false,largeText:false,focusStyle:'halo',
 autoplay:true,resume:true,playbackRate:1,controlsTimeout:6,playNext:false,repeatMode:'off',
 clock24:false,showClock:true,sleepMinutes:0,idleMinutes:0,rememberHistory:true,startupPage:'home',
 showSamples:true,sortOrder:'added',thumbnailSize:'comfortable',photoInterval:6,photoRepeat:true,photoFit:'contain'
};
export const RANGES={brightness:[70,130,5],contrast:[70,140,5],saturation:[0,150,5],volume:[0,100,5],navVolume:[0,100,5],bass:[-12,12,2],treble:[-12,12,2],balance:[-100,100,10]};
export const SCHEMA={...RANGES,pictureMode:['standard','cinema','vivid'],temperature:['neutral','warm','cool'],videoFit:['contain','cover'],
 accent:['lavender','mint','amber','blue'],theme:['midnight','slate','oled'],muted:'boolean',navSounds:'boolean',audioPath:['direct','enhanced'],
 soundMode:['standard','cinema','dialogue','night'],monoAudio:'boolean',captions:'boolean',captionSize:['small','medium','large'],captionBackground:['dark','solid','clear'],
 highContrast:'boolean',reducedMotion:'boolean',largeText:'boolean',focusStyle:['halo','outline'],autoplay:'boolean',resume:'boolean',playbackRate:[.5,.75,1,1.25,1.5,2],controlsTimeout:[0,4,6,10],
 playNext:'boolean',repeatMode:['off','one','all'],clock24:'boolean',showClock:'boolean',sleepMinutes:[0,5,15,30,60,90],idleMinutes:[0,5,15,30],rememberHistory:'boolean',startupPage:['home','videos','photos','music','saved'],
 showSamples:'boolean',sortOrder:['added','title','duration'],thumbnailSize:['comfortable','compact'],photoInterval:[3,6,10,15,30],photoRepeat:'boolean',photoFit:['contain','cover']};
export function validateSettings(input,{strict=false}={}){
 const out={...DEFAULT_SETTINGS};
 if(!input||typeof input!=='object'||Array.isArray(input)){if(strict)throw Error('Settings must be an object.');return out;}
 for(const[key,value]of Object.entries(input)){
  if(!Object.hasOwn(SCHEMA,key)){if(strict)throw Error('Invalid setting: '+key);continue;}
  const rule=SCHEMA[key];let valid=false;
  if(rule==='boolean')valid=typeof value==='boolean';
  else if(RANGES[key]){const[min,max,step]=RANGES[key];valid=typeof value==='number'&&Number.isFinite(value)&&value>=min&&value<=max&&(value-min)%step===0;}
  else if(Array.isArray(rule))valid=rule.includes(value);
  if(valid)out[key]=value;else if(strict)throw Error('Invalid setting: '+key);
 }
 return out;
}
