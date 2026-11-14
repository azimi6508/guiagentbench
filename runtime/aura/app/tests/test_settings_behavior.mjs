import assert from 'node:assert/strict';
import {test} from 'node:test';

const storageValues=new Map();
const memoryStorage={getItem:key=>storageValues.get(key)??null,setItem:(key,value)=>storageValues.set(key,value),removeItem:key=>storageValues.delete(key)};
globalThis.localStorage=memoryStorage;
const data=await import('../src/data.js');
const store=await import('../src/store.js');
const settings=await import('../src/settings.js');
const {AudioEngine}=await import('../src/audio.js');
let moduleSequence=0;
async function restartWith(raw){
 storageValues.clear();storageValues.set(store.STORAGE_KEY,typeof raw==='string'?raw:JSON.stringify(raw));
 return import(`../src/store.js?restart=${++moduleSequence}`);
}
const validLink=()=>({id:'r_aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',title:'A film',kind:'video',url:'https://example.com/film.webm',added:100});

test('one damaged stored setting preserves valid preferences, favorites and positions',async()=>{
 const raw=store.fresh();raw.settings.volume='too loud';raw.settings.theme='slate';raw.profile='guest';
 raw.profiles.guest.watchlist=['p-coffee'];raw.profiles.guest.history['v-coffee']={time:4,duration:20,updated:123};
 const recovered=await restartWith(raw);
 assert.equal(recovered.state.settings.volume,data.DEFAULT_SETTINGS.volume);
 assert.equal(recovered.state.settings.theme,'slate');assert.equal(recovered.state.profile,'guest');
 assert.deepEqual(recovered.state.profiles.guest.watchlist,['p-coffee']);
 assert.deepEqual(recovered.state.profiles.guest.history['v-coffee'],raw.profiles.guest.history['v-coffee']);
 assert.equal(recovered.storageRecovered,true);assert.equal(recovered.storageAvailable,true);
 assert.deepEqual(store.validateState(JSON.parse(storageValues.get(store.STORAGE_KEY))),recovered.state);
});

test('malformed stored JSON is distinct from unavailable browser storage',async()=>{
 const recovered=await restartWith('{broken JSON');
 assert.deepEqual(recovered.state,store.fresh());assert.equal(recovered.storageAvailable,true);
 assert.equal(recovered.storageRecovered,true);assert.doesNotThrow(()=>JSON.parse(storageValues.get(store.STORAGE_KEY)));
});

test('stored recovery drops invalid history and links without removing other profiles',async()=>{
 const raw=store.fresh();raw.profiles.alex.watchlist=['bad-id','p-coffee','p-coffee'];
 raw.profiles.alex.history['v-coffee']={time:99,duration:20,updated:100};
 raw.profiles.guest.watchlist=['p-liftoff'];raw.links=[validLink(),{...validLink(),id:'invalid'}];
 raw.settings=JSON.parse('{"theme":"slate","constructor":true,"__proto__":{"polluted":true}}');
 const recovered=await restartWith(raw);
 assert.deepEqual(recovered.state.profiles.alex.watchlist,['p-coffee']);
 assert.deepEqual(recovered.state.profiles.alex.history,{});
 assert.deepEqual(recovered.state.profiles.guest.watchlist,['p-liftoff']);
 assert.equal(recovered.state.links.length,1);assert.equal(recovered.state.settings.theme,'slate');
 assert.equal({}.polluted,undefined);
});

test('invalid backup history is rejected before the live state changes',()=>{
 store.resetAll();store.setting('volume',80);const before=JSON.stringify(store.state);
 for(const entry of [{time:2,duration:0,updated:1},{time:21,duration:20,updated:1},{time:1,duration:20,updated:-1}]){
  const backup=store.fresh();backup.profiles.alex.history['v-coffee']=entry;
  assert.throws(()=>store.replaceState(backup),/history/);assert.equal(JSON.stringify(store.state),before);
 }
});

test('backup media link dates, titles and UUIDs are validated without coercion',()=>{
 for(const patch of [{added:Infinity},{added:NaN},{added:null},{added:-1},{added:'100'},{title:'   '},{id:'r_'+'-'.repeat(36)}]){
  const backup=store.fresh();backup.links=[{...validLink(),...patch}];assert.throws(()=>store.validateState(backup));
 }
 const backup=store.fresh();backup.links=[validLink()];assert.equal(store.validateState(backup).links[0].added,100);
});

test('every persisted setting has a labeled control and only its category is reset',()=>{
 for(const key of Object.keys(data.SCHEMA))assert.ok(settings.definition(key),`Missing setting control: ${key}`);
 const picture=settings.categoryDefaults('picture');assert.ok('brightness' in picture);assert.ok(!('volume' in picture));
 assert.deepEqual(settings.categoryDefaults('unknown'),{});
});

test('sound settings state when controls require Enhanced processing',()=>{
 store.resetAll();assert.match(settings.contextPanel('sound'),/Direct sound/);
 assert.match(settings.categoryRows('sound'),/Used with Enhanced audio/);
 store.setting('audioPath','enhanced');assert.doesNotMatch(settings.categoryRows('sound'),/Used with Enhanced audio/);
 assert.match(settings.contextPanel('sound'),/Enhanced/);
 const slider=settings.dialogForSetting('volume');assert.match(slider.html,/--range-progress:65%/);
 assert.match(slider.html,/aria-valuetext="65%"/);
});

// A small AudioContext lifecycle double. These are graph/control regressions,
// not claims about codec decoding or physical speaker output.
class Param {
 constructor(value=0){this.value=value;}
 setTargetAtTime(value){this.value=value;}
 setValueAtTime(value){this.value=value;}
 linearRampToValueAtTime(value){this.value=value;}
 exponentialRampToValueAtTime(value){this.value=value;}
}
class Node {
 constructor(){this.connections=[];for(const key of ['gain','frequency','Q','pan','threshold','knee','ratio','attack','release'])this[key]=new Param();}
 connect(target){this.connections.push(target);return target;}
 disconnect(){this.connections=[];}
 start(){this.started=true;}
 stop(){this.stopped=true;}
 getFloatTimeDomainData(samples){samples.fill(0);}
}
class Context {
 constructor(){this.state='running';this.currentTime=1;this.destination=new Node();this.oscillators=[];this.sources=[];}
 createGain(){return new Node();}
 createBiquadFilter(){return new Node();}
 createDynamicsCompressor(){return new Node();}
 createStereoPanner(){return new Node();}
 createAnalyser(){return new Node();}
 createOscillator(){const node=new Node();this.oscillators.push(node);return node;}
 createMediaElementSource(){const node=new Node();this.sources.push(node);return node;}
 async resume(){this.state='running';}
 async close(){this.state='closed';}
}
function engineWith(ContextClass=Context,patch={}){
 globalThis.window={AudioContext:ContextClass};
 const preferences={...data.DEFAULT_SETTINGS,...patch},errors=[];
 return {engine:new AudioEngine(()=>preferences,error=>errors.push(error)),preferences,errors};
}

test('native sound remains available when the Web Audio API is missing',async()=>{
 const {engine,errors}=engineWith();globalThis.window={};
 const video={};assert.equal(engine.attach(video),false);assert.equal(video.volume,.65);assert.equal(video.muted,false);
 assert.equal(await engine.sample(),false);assert.equal(errors.length,1);
});

test('Direct sample and navigation sound bypass Enhanced equalization and panning',async()=>{
 const {engine,preferences}=engineWith(Context,{bass:12,balance:100,monoAudio:true,soundMode:'cinema'});
 await engine.unlock();assert.equal(engine.direct.gain.value,1);assert.equal(engine.processed.gain.value,0);
 preferences.audioPath='enhanced';engine.update();
 assert.equal(engine.direct.gain.value,0);assert.equal(engine.processed.gain.value,1);
 preferences.muted=true;engine.update();assert.equal(engine.master.gain.value,0);
 preferences.muted=false;preferences.volume=35;engine.update();assert.equal(engine.master.gain.value,.35);
});

test('a detached Enhanced media element reconnects without a second media source',async()=>{
 const {engine}=engineWith(Context,{audioPath:'enhanced'});await engine.unlock();
 const video={};assert.equal(engine.attach(video),true);const source=engine.context.sources[0];
 engine.detach(video);assert.equal(source.connections.length,0);
 assert.equal(engine.attach(video),true);assert.equal(source.connections.length,1);assert.equal(engine.context.sources.length,1);
});

test('canceling a sample while audio permission resumes cannot start sound later',async()=>{
 class PendingContext extends Context {
  constructor(){super();this.state='suspended';}
  resume(){return new Promise(resolve=>this.finish=()=>{this.state='running';resolve();});}
 }
 const {engine}=engineWith(PendingContext);const pending=engine.sample();
 engine.stopSample();engine.context.finish();assert.equal(await pending,false);
 assert.equal(engine.context.oscillators.length,0);assert.equal(engine.sampleUntil,0);
});

test('a second sample click cancels its first pending start',async()=>{
 class PendingContext extends Context {
  constructor(){super();this.state='suspended';}
  resume(){return new Promise(resolve=>this.finish=()=>{this.state='running';resolve();});}
 }
 const {engine}=engineWith(PendingContext);const first=engine.sample();assert.equal(await engine.sample(),false);
 engine.context.finish();assert.equal(await first,false);assert.equal(engine.context.oscillators.length,0);
});

test('failed graph initialization never leaves a broken cached context',async()=>{
 class UnsupportedContext extends Context {createStereoPanner(){throw Error('Unavailable');}}
 const {engine}=engineWith(UnsupportedContext,{audioPath:'enhanced'});
 assert.equal(await engine.unlock(),false);assert.equal(engine.context,null);
 const video={};assert.equal(engine.attach(video),false);assert.equal(video.volume,.65);
});

test('remote feedback does not schedule tones before a user gesture or when disabled',async()=>{
 const {engine,preferences}=engineWith();await engine.navigation();assert.equal(engine.context,null);
 await engine.unlock();preferences.navSounds=false;await engine.navigation();assert.equal(engine.context.oscillators.length,0);
 preferences.navSounds=true;await engine.navigation();assert.equal(engine.context.oscillators.length,1);
});
