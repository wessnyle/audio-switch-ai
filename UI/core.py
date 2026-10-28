"""Settings shared by the Windows interface and its regression tests."""
from copy import deepcopy

VERSION = '2.1.0-beta.1'
ACTIONS = [
    ('Process & clean audio','process'),('Convert format / sample rate','convert'),
    ('Extract vocals','vocals'),('Extract lead vocal · experimental','lead'),
    ('Create instrumental','instrumental'),('Separate vocals, drums, bass & other','stems'),
    ('Extract audio from video','extract'),('Inspect audio / estimate BPM & key','inspect'),
    ('Join files in list order','join'),('Split into equal-length parts','split'),
]
DEFAULTS = dict(action='process',outputFormat='wav',sampleRate=0,bitDepth=24,
    dereverb=False,dereverbStrength=.7,noiseReduction=False,noiseMode='voice',
    noiseStrength=12.,deess=False,declick=False,declip=False,humHz=0,rumbleHz=0,
    normalize=False,lufs=-16.,peakNormalize=False,peakDB=-1.,gainDB=0.,
    channels='preserve',trimSilence=False,silenceDB=-50.,fadeIn=0.,fadeOut=0.,
    tempo=1.,semitones=0.,reverse=False,splitSeconds=60.,clipStart=0.,clipLength=0.)
PRESETS = {
    'Clean vocal':dict(action='vocals',dereverb=True,noiseReduction=True,noiseStrength=8.),
    'Podcast cleanup':dict(noiseReduction=True,rumbleHz=80,deess=True,normalize=True,lufs=-16.),
    'Ready for DAW':dict(action='convert',sampleRate=48000,bitDepth=24),
    'Karaoke':dict(action='instrumental'),'Reset':{},
}
QUICK_ACTIONS = [('Process Audio with AI','process'),('Extract Vocals (AI)','vocals'),
    ('Reduce Reverb (AI)','dereverb'),('Remove Noise (AI)','denoise'),
    ('Convert to WAV','wav'),('Change Sample Rate','rate')]

def preset(name, saved=None):
    return {**deepcopy(DEFAULTS),**(PRESETS.get(name,(saved or {}).get(name,{})))}

def quick_settings(mode):
    options=deepcopy(DEFAULTS)
    if mode in ['vocals','instrumental','lead','stems','convert']:options['action']=mode
    elif mode=='dereverb':options['dereverb']=True
    elif mode=='denoise':options['noiseReduction']=True
    elif mode=='wav':options['action']='convert'
    elif mode=='rate':options.update(action='convert',outputFormat='original',bitDepth=0)
    return options

def preview_options(options):
    # Windows PlaySound uses a simple PCM preview, independent of the chosen export codec.
    return {**options,'outputFormat':'wav','bitDepth':16}
