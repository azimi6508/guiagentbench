"""Recreate the bundled photographic motion studies and original stereo scores.
Development-only: Pillow, numpy, scikit-image, FFmpeg. Not needed to run AURA.
Also creates H.264/AAC MP4 and stereo MP3 alternatives for browser compatibility.
"""
from pathlib import Path
import subprocess, wave, json, math
import numpy as np
from PIL import Image
import skimage
ROOT=Path(__file__).resolve().parents[1]
SOURCE=Path(skimage.__file__).parent/'data'
OUT=ROOT/'assets'

def build_fallbacks(media_directory, ident):
 """Derive alternate containers/codecs from the same finished motion and music.

 The original WebM uses full-range BT.601 colors. Convert its range and matrix
 for a limited-range BT.709 MP4, constrained-baseline H.264 Level 3.1, yuv420p,
 stereo AAC-LC, with the MP4 index at the front for immediate local playback.
 These files are prebuilt; the application server never invokes FFmpeg.
 """
 subprocess.run([
  'ffmpeg','-hide_banner','-loglevel','error',
  '-i',str(media_directory/f'{ident}.webm'),'-map','0:v:0','-map','0:a:0',
  '-vf','scale=in_range=full:out_range=limited:in_color_matrix=bt601:out_color_matrix=bt709,format=yuv420p',
  '-c:v','libx264','-profile:v','baseline','-level:v','3.1',
  '-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',
  '-preset','medium','-crf','21','-c:a','aac','-b:a','160k','-movflags','+faststart',
  '-y',str(media_directory/f'{ident}.mp4')],check=True)
 subprocess.run([
  'ffmpeg','-hide_banner','-loglevel','error',
  '-i',str(media_directory/f'{ident}.ogg'),'-map','0:a:0','-c:a','libmp3lame','-q:a','2',
  '-y',str(media_directory/f'{ident}.mp3')],check=True)

photos=[('deep-field','hubble_deep_field.jpg','Deep field','NASA / ESA / STScI'),
 ('liftoff','rocket.jpg','The moment before','SpaceX'),
 ('coffee','coffee.png','Morning ritual','Rachel Michetti / Pikolo Espresso Bar'),
 ('portrait','astronaut.png','A life beyond Earth','NASA'),
 ('chelsea','chelsea.png','In good company','Stefan van der Walt')]
for ident,filename,title,credit in photos:
 im=Image.open(SOURCE/filename).convert('RGB')
 im.save(OUT/'photos'/f'{ident}.jpg',quality=94)
# Soundtracks contain different progressions and melodies, not a repeated tone.
RATE=48000
tracks=[('deep-field',24,[48,55,60,64],[72,76,79,83,81,79,76,74],4),
 ('liftoff',22,[50,57,62,65],[74,77,81,86,84,81,77,74],7),
 ('coffee',20,[53,60,65,69],[77,81,84,88,86,84,81,79],11)]
for ident,duration,chord,melody,seed in tracks:
 rng=np.random.default_rng(seed)
 n=duration*RATE;t=np.arange(n)/RATE; stereo=np.zeros((n,2))
 for k,note in enumerate(chord):
  f=440*2**((note-69)/12)
  pad=.065*np.sin(2*np.pi*f*t+.12*np.sin(2*np.pi*.13*t)) + .018*np.sin(2*np.pi*(2*f+.4)*t)
  amp=(.65+.35*np.sin(np.pi*t/duration))
  stereo[:,0]+=pad*amp*(.7 if k%2 else 1)
  stereo[:,1]+=pad*amp*(1 if k%2 else .7)
 for k,start in enumerate(np.arange(.7,duration-1.3,.65 if ident=='liftoff' else .9)):
  f=440*2**((melody[k%len(melody)]-69)/12)
  tt=t-start
  env=np.where(tt>=0,(1-np.exp(-np.maximum(tt,0)*40))*np.exp(-np.maximum(tt,0)*2),0)
  tone=(np.sin(2*np.pi*f*tt)+.28*np.sin(2*np.pi*2*f*tt))*.16*env
  stereo[:,0]+=tone*(.7 if k%2 else 1)
  stereo[:,1]+=tone*(1 if k%2 else .7)
 fade=np.minimum(np.clip(t/.8,0,1),np.clip((duration-t)/1.4,0,1))
 stereo*=fade[:,None]
 stereo=np.tanh(stereo*1.25)
 stereo*=.76/max(.76,np.abs(stereo).max())
 wav=OUT/'media'/f'{ident}.wav'
 with wave.open(str(wav),'wb') as w:
  w.setnchannels(2);w.setsampwidth(2);w.setframerate(RATE);w.writeframes((stereo*32767).astype('<i2').tobytes())
 photo=OUT/'photos'/f'{ident}.jpg';movie=OUT/'media'/f'{ident}.webm'
 frames=duration*24
 vf=f"scale=1920:-1,zoompan=z='1.03+0.10*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s=1280x720:fps=24,fade=t=in:st=0:d=0.6,fade=t=out:st={duration-1}:d=1"
 subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(photo),'-i',str(wav),'-vf',vf,'-t',str(duration),'-c:v','libvpx-vp9','-b:v','0','-crf','34','-deadline','realtime','-cpu-used','6','-threads','2','-pix_fmt','yuv420p','-c:a','libopus','-b:a','128k',str(movie)],check=True)
 subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(wav),'-c:a','libopus','-b:a','128k',str(OUT/'media'/f'{ident}.ogg')],check=True)
 wav.unlink()
 build_fallbacks(OUT/'media',ident)
 print(ident, movie.stat().st_size,flush=True)
