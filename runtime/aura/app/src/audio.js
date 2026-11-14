/** One audio graph for media and interface sounds. No sound is scheduled before
 * a user gesture successfully resumes the context. Hardware volume is untouched.
 */
export class AudioEngine {
  constructor(getSettings,onError=()=>{}) {
    this.getSettings=getSettings;this.onError=onError;
    this.context=null;this.mediaNodes=new WeakMap();this.sampleNodes=[];
    this.nativeVideo=null;this.lastNav=0;this.sampleUntil=0;this.unlocked=false;
    this.samplePending=false;this.sampleRequest=0;
  }
  ensure() {
    if(this.context)return this.context;
    const Audio=window.AudioContext||window.webkitAudioContext;
    if(!Audio)return null;
    let c;
    try {
      c=new Audio();
      const input=c.createGain();
      const low=c.createBiquadFilter();low.type='lowshelf';low.frequency.value=200;
      const mid=c.createBiquadFilter();mid.type='peaking';mid.frequency.value=2200;mid.Q.value=.8;
      const high=c.createBiquadFilter();high.type='highshelf';high.frequency.value=3500;
      const compressor=c.createDynamicsCompressor();
      const fold=c.createGain();fold.channelCountMode='explicit';
      const panner=c.createStereoPanner();
      const processed=c.createGain(),direct=c.createGain(),master=c.createGain();
      const enhanced=this.getSettings().audioPath==='enhanced';
      processed.gain.value=enhanced?1:0;direct.gain.value=enhanced?0:1;master.gain.value=0;
      const analyser=c.createAnalyser();analyser.fftSize=1024;
      input.connect(low).connect(mid).connect(high).connect(compressor)
        .connect(fold).connect(panner).connect(processed).connect(master);
      // Direct samples/remote sounds match Direct playback: no hidden EQ or pan.
      input.connect(direct).connect(master);
      master.connect(analyser).connect(c.destination);
      Object.assign(this,{context:c,input,low,mid,high,compressor,fold,panner,processed,direct,master,analyser});
      this.levelSamples=new Float32Array(analyser.fftSize);
      this.update();return c;
    } catch {
      // A partial graph must never become a cached, unusable AudioContext.
      if(c)try{c.close().catch(()=>{});}catch{/* The context may already be closed. */}
      this.context=null;return null;
    }
  }
  async unlock() {
    try {
      const c=this.ensure();if(!c)return false;
      if(c.state!=='running')await c.resume();
      this.unlocked=c.state==='running';return this.unlocked;
    } catch {
      this.unlocked=false;
      this.onError('Audio could not start. Check the browser’s sound permission.');return false;
    }
  }
  attach(video,forceDirect=false) {
    if(forceDirect||this.getSettings().audioPath==='direct'){
      this.nativeVideo=video;this.update();return false;
    }
    try {
      const c=this.ensure();
      if(!c||c.state!=='running'){
        this.nativeVideo=video;this.update();
        this.onError('Using direct sound. Enhanced audio is not ready.');return false;
      }
      let source=this.mediaNodes.get(video);
      if(!source){source=c.createMediaElementSource(video);this.mediaNodes.set(video,source);}
      // detach() disconnects the source; reusing that element must reconnect it.
      source.disconnect();source.connect(this.input);
      if(this.nativeVideo===video)this.nativeVideo=null;
      video.volume=1;video.muted=false;this.update();return true;
    } catch {
      this.nativeVideo=video;this.update();
      this.onError('Enhanced audio is unavailable. Using direct sound.');return false;
    }
  }
  detach(video) {
    this.mediaNodes.get(video)?.disconnect();
    if(this.nativeVideo===video)this.nativeVideo=null;
  }
  update() {
    const s=this.getSettings(),c=this.context;
    if(this.nativeVideo){this.nativeVideo.volume=s.volume/100;this.nativeVideo.muted=s.muted;}
    if(!c)return;
    const preset={standard:[0,0,0],cinema:[4,0,2],dialogue:[-3,5,-1],night:[-4,2,-2]}[s.soundMode];
    const set=(param,value)=>param.setTargetAtTime(value,c.currentTime,.025);
    set(this.low.gain,preset[0]+s.bass);set(this.mid.gain,preset[1]);set(this.high.gain,preset[2]+s.treble);
    const night=s.soundMode==='night';
    set(this.compressor.threshold,night?-30:-10);set(this.compressor.knee,night?25:12);
    set(this.compressor.ratio,night?8:3);set(this.compressor.attack,.006);set(this.compressor.release,.25);
    this.fold.channelCount=s.monoAudio?1:2;
    const enhanced=s.audioPath==='enhanced';
    set(this.processed.gain,enhanced?1:0);set(this.direct.gain,enhanced?0:1);
    set(this.panner.pan,s.balance/100);set(this.master.gain,s.muted?0:s.volume/100);
  }
  async navigation() {
    const s=this.getSettings();
    if(!this.unlocked||!s.navSounds||s.muted||s.volume===0||s.navVolume===0)return;
    const c=this.context;if(!c||c.state!=='running')return;
    if(c.currentTime-this.lastNav<.06)return;this.lastNav=c.currentTime;
    this.note(740,c.currentTime,.055,.08*s.navVolume/100,0,'sine');
  }
  note(frequency,time,length,amplitude,pan=0,type='sine') {
    const c=this.context,osc=c.createOscillator(),gain=c.createGain(),position=c.createStereoPanner();
    osc.type=type;osc.frequency.value=frequency;position.pan.value=pan;
    osc.connect(gain).connect(position).connect(this.input);
    gain.gain.setValueAtTime(0,time);gain.gain.linearRampToValueAtTime(amplitude,time+.015);
    gain.gain.exponentialRampToValueAtTime(.0001,time+length);
    osc.start(time);osc.stop(time+length+.04);
    osc.onended=()=>{osc.disconnect();gain.disconnect();position.disconnect();};
    return osc;
  }
  async sample() {
    if(this.samplePending||this.sampleUntil>Date.now()){this.stopSample();return false;}
    const s=this.getSettings();
    if(s.muted||!s.volume){this.onError('Unmute AURA and raise the app volume to hear the sound sample.');return false;}
    this.stopSample();const request=this.sampleRequest;this.samplePending=true;
    const unlocked=await this.unlock();
    // A second click, navigation away, or standby cancels a pending sample too.
    if(request!==this.sampleRequest)return false;
    this.samplePending=false;
    if(!unlocked){this.onError('Sound is unavailable. Allow audio for this page in your browser.');return false;}
    const current=this.getSettings();
    if(current.muted||!current.volume)return false;
    const time=this.context.currentTime+.02;
    [[261.63,0,-.6],[329.63,.25,.6],[392,.5,-.3],[523.25,.85,.3],[659.25,1.1,0]].forEach(([frequency,delay,pan])=>{
      this.sampleNodes.push(this.note(frequency,time+delay,.9,.22,pan));
      this.sampleNodes.push(this.note(frequency*2,time+delay,.65,.035,pan));
    });
    this.sampleUntil=Date.now()+2150;return true;
  }
  stopSample() {
    this.sampleRequest++;this.samplePending=false;
    for(const node of this.sampleNodes){try{node.stop();}catch{/* A naturally ended note is already stopped. */}}
    this.sampleNodes=[];this.sampleUntil=0;
  }
  level() {
    if(!this.analyser||this.context?.state!=='running')return 0;
    this.analyser.getFloatTimeDomainData(this.levelSamples);
    return Math.sqrt(this.levelSamples.reduce((sum,value)=>sum+value*value,0)/this.levelSamples.length);
  }
}
