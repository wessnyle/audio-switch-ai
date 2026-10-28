"""Measured regression checks, run with the bundled Python on Windows or macOS."""
import argparse, hashlib, importlib, json, os, subprocess, sys, tempfile, time
from pathlib import Path

def emit(message):print(json.dumps({'type':'check','message':message}),flush=True)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resources',required=True);parser.add_argument('--ai',action='store_true');args=parser.parse_args()
    resources=Path(args.resources).resolve();exe=resources/'Runtime/python.exe' if os.name=='nt' else Path(sys.executable)
    sys.path.insert(0,str(resources/'Backend'));sys.path.insert(0,str(resources/'UI'))
    import numpy as np
    import soundfile as sf
    import worker
    worker.ROOT=resources
    worker.CANCEL_FILE=None
    for module in ['torch','torchvision','onnxruntime','audio_separator.separator','audio_separator.separator.architectures.mdxc_separator','vendor.scnet','librosa','soxr','PySide6.QtWidgets']:
        importlib.import_module(module)
        emit('Import OK: '+module)
    from core import DEFAULTS,preview_options,quick_settings
    assert quick_settings('dereverb')['dereverb'] and quick_settings('denoise')['noiseReduction']
    assert preview_options(DEFAULTS)['bitDepth']==16
    from windows_integration import registry_commands,ps_literal
    quoted=registry_commands(Path(r'C:\Users\Tést & Co\Audio Switch AI.exe'))
    assert all('"%1"' in command and 'cmd.exe' not in command for _,command in quoted)
    assert ps_literal("a'b") == "'a''b'"
    with tempfile.TemporaryDirectory(prefix='AudioSwitchAI-engine-check-') as name:
        root=Path(name);rate=48000;t=np.arange(rate*2)/rate
        signal=np.stack([.2*np.sin(2*np.pi*440*t),.1*np.sin(2*np.pi*880*t)],axis=1)
        source=root/"Friend's test [stereo] & café.wav";sf.write(source,signal,rate,subtype='PCM_24')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        def run(extra,inputs=None,preview=False,success=True,timeout=240):
            request=root/'request.json';job={'inputs':[str(p) for p in (inputs or [source])],'options':{**DEFAULTS,**extra},'preview':preview,'previewDirectory':str(root)}
            request.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
            result=subprocess.run([str(exe),'-I','-X','utf8',str(resources/'Backend/worker.py'),'--resources',str(resources),'--request',str(request)],capture_output=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            events=[json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
            if (result.returncode==0)!=success:raise AssertionError(f'{extra}: {result.stdout}\n{result.stderr}')
            outputs=[Path(p) for e in events if e.get('type')=='result' for p in e.get('outputs',[])]
            assert not list(root.glob('.AudioSwitchAI-*')),'Temporary files leaked'
            return outputs,events
        outputs,_=run({'gainDB':-6});data,sr=sf.read(outputs[0]);assert sr==rate
        assert abs(20*np.log10(np.max(np.abs(data))/.2)+6)<.03
        first=outputs[0];second,_=run({'gainDB':-6});assert second[0]!=first and first.exists()
        emit('PASS: measured gain, Unicode / punctuation filenames, collision-safe output')
        for fmt in ['wav','aiff','caf','flac','aac','alac','mp3','ogg','opus']:
            outputs,_=run({'action':'convert','outputFormat':fmt,'sampleRate':48000});stream,_=worker.probe(outputs[0]);assert int(stream['sample_rate'])==48000 and int(stream['channels'])==2
        outputs,_=run({'sampleRate':96000,'bitDepth':24});assert sf.info(outputs[0]).samplerate==96000
        emit('PASS: all nine export formats and 96 kHz conversion')
        for channel,expected in [('mono',signal.mean(axis=1)),('left',signal[:,0]),('right',signal[:,1]),('swap',signal[:,::-1])]:
            outputs,_=run({'channels':channel});data,_=sf.read(outputs[0]);assert np.max(np.abs(data-expected))<3e-6
        outputs,_=run({'channels':'split'});assert len(outputs)==2
        outputs,_=run({'reverse':True});data,_=sf.read(outputs[0]);assert np.max(np.abs(data-signal[::-1]))<3e-6
        outputs,_=run({'clipStart':.3,'clipLength':.7});assert abs(sf.info(outputs[0]).duration-.7)<.002
        outputs,_=run({'tempo':1.5});assert abs(sf.info(outputs[0]).duration-2/1.5)<.05
        outputs,_=run({'semitones':12});data,sr=sf.read(outputs[0]);assert abs(len(data)/sr-2)<.05
        segment=data[2400:-2400,0];freq=np.fft.rfftfreq(len(segment),1/sr);assert abs(freq[np.argmax(abs(np.fft.rfft(segment)))]-880)<3
        outputs,_=run({'peakNormalize':True,'peakDB':-3});data,_=sf.read(outputs[0]);assert abs(20*np.log10(abs(data).max())+3)<.03
        outputs,_=run({'normalize':True,'lufs':-16});_,events=run({'action':'inspect'},inputs=outputs)
        report=next(e['report'] for e in events if e.get('report'));assert abs(float(report.split('Integrated loudness: ')[1].split()[0])+16)<.3
        emit('PASS: channel math, reverse, excerpts, tempo, pitch, peak and LUFS normalization')
        padded=root/'padded.wav';sf.write(padded,np.concatenate([np.zeros((12000,2)),signal,np.zeros((24000,2))]),rate,subtype='PCM_24')
        outputs,_=run({'trimSilence':True},inputs=[padded]);assert 1.95<sf.info(outputs[0]).duration<2.2
        outputs,_=run({'fadeIn':.5,'fadeOut':.5});data,_=sf.read(outputs[0]);assert abs(data[:1000]).max()<.02 and abs(data[-1000:]).max()<.02
        outputs,_=run({'action':'split','splitSeconds':1.1});assert len(outputs)==2 and abs(sum(sf.info(p).duration for p in outputs)-2)<.003
        outputs,_=run({'action':'join'},inputs=[source,source]);assert abs(sf.info(outputs[0]).duration-4)<.003
        rng=np.random.default_rng(42);noise=rng.normal(0,.006,(rate*2,2));noisy=root/'noise.wav';sf.write(noisy,noise,rate,subtype='PCM_24')
        for mode in ['voice','music','steady']:
            outputs,_=run({'noiseReduction':True,'noiseMode':mode,'noiseStrength':20},inputs=[noisy]);data,_=sf.read(outputs[0]);assert np.sqrt((data**2).mean())<np.sqrt((noise**2).mean())*.8
        run({'declick':True,'declip':True,'deess':True,'humHz':60,'rumbleHz':80})
        emit('PASS: fades, end trimming, split / join, AI noise modes and repair filters')
        outputs,events=run(preview_options({'gainDB':-3}),preview=True);assert sf.info(outputs[0]).subtype=='PCM_16'
        reference=next(Path(e['reference']) for e in events if e.get('reference'));assert sf.info(reference).subtype=='PCM_16'
        run({'sampleRate':7000},success=False)
        broken=root/'broken.wav';broken.write_text('broken audio',encoding='utf-8')
        outputs,events=run({},inputs=[broken,source],success=False);assert len(outputs)==1 and any(e['type']=='error' for e in events)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==digest
        emit('PASS: playable previews, invalid inputs, mixed batches, unchanged originals')
        if args.ai:
            short=root/'AI short.wav';sf.write(short,signal[:rate],rate,subtype='PCM_24')
            for extra in [{'action':'vocals'},{'action':'lead'},{'action':'stems'},{'action':'instrumental'},{'dereverb':True}]:
                emit('Running bundled AI check: '+str(extra))
                outputs,_=run(extra,inputs=[short],timeout=1200)
                assert len(outputs)==(4 if extra.get('action')=='stems' else 1)
                for path in outputs:
                    data,sr=sf.read(path);assert sr==rate and np.isfinite(data).all() and abs(len(data)/sr-1)<.1
                emit('PASS: AI '+str(extra))
    emit('ALL ENGINE CHECKS PASSED')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:
        import traceback
        traceback.print_exc();emit('ENGINE CHECK FAILED — see the diagnostic log');sys.exit(1)
