#!/usr/bin/env python3
"""Offline processing worker. Communicates with the native app using JSON lines."""
from __future__ import annotations
import argparse
import ctypes
import errno
import gc
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import traceback

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
CHILD = None
CANCELLED = False
CURRENT_INDEX = 0
CURRENT_TOTAL = 1
MODEL_CACHE = None
CANCEL_FILE = None

def tool(name):
    return ROOT / 'Tools/bin' / (name + ('.exe' if os.name == 'nt' else ''))

def check_cancelled():
    if CANCELLED or (CANCEL_FILE and CANCEL_FILE.exists()):
        raise InterruptedError('Processing stopped.')

def emit(kind, **data):
    print(json.dumps({'type': kind, **data}, ensure_ascii=False, allow_nan=False), flush=True)

def status(message, progress=None):
    check_cancelled()
    values = {'message': message, 'index': CURRENT_INDEX}
    if progress is not None:
        values['progress'] = max(0, min(1, (CURRENT_INDEX + progress) / CURRENT_TOTAL))
    emit('progress', **values)

def stop(signum, frame):
    global CANCELLED
    CANCELLED = True
    if CHILD is not None and CHILD.poll() is None:
        CHILD.terminate()
    raise InterruptedError('Processing stopped.')

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def command(args):
    global CHILD
    if CANCELLED:
        raise InterruptedError('Processing stopped.')
    check_cancelled()
    CHILD = subprocess.Popen([str(x) for x in args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try:
        stdout, stderr = CHILD.communicate()
        check_cancelled()
        if CHILD.returncode:
            raise RuntimeError(stderr.decode('utf-8', 'replace')[-2400:].strip() or 'The audio tool could not complete this operation.')
        return stdout.decode('utf-8', 'replace'), stderr.decode('utf-8', 'replace')
    finally:
        if CHILD.poll() is None:
            CHILD.terminate()
            CHILD.wait()
        CHILD = None

def ffmpeg(*args):
    return command([tool('ffmpeg'), '-hide_banner', '-nostdin', '-loglevel', 'error', *args])

def probe(path):
    data, _ = command([tool('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path])
    data = json.loads(data)
    stream = next((s for s in data['streams'] if s.get('codec_type') == 'audio'), None)
    if stream is None:
        raise ValueError('This file has no readable audio track.')
    return stream, data.get('format', {})

def duration(path):
    stream, container = probe(path)
    return float(stream.get('duration', container.get('duration', 0)))

def decode(source, dest, rate=None, channels=None, start=0, length=0):
    args = ['-n', '-i', source, '-map', '0:a:0', '-vn']
    if start > 0:
        args += ['-ss', str(start)]
    if length > 0:
        args += ['-t', str(length)]
    if rate:
        args += ['-ar', str(rate)]
    if channels:
        args += ['-ac', str(channels)]
    ffmpeg(*args, '-c:a', 'pcm_f32le', dest)

def array_read(path):
    import numpy as np
    import soundfile as sf
    audio, rate = sf.read(path, dtype='float32', always_2d=True)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError('The decoded audio is empty or contains invalid samples.')
    return audio, rate

def array_write(path, audio, rate):
    import numpy as np
    import soundfile as sf
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError('Processing produced invalid audio. No output was saved.')
    sf.write(path, audio, rate, subtype='FLOAT')

def resample_array(audio, original, target):
    if original == target:
        return audio
    import soxr
    return soxr.resample(audio, original, target, quality='HQ')

def separator_for(name, output):
    """Use the packaged architecture loader, with all model discovery strictly local."""
    global MODEL_CACHE
    from audio_separator.separator import Separator
    class OfflineSeparator(Separator):
        def download_model_files(self, filename):
            folder = ROOT / 'Models' / name
            manifest = json.loads((folder / 'manifest.json').read_text())
            model = folder / manifest['filename']
            config = folder / 'config.yaml'
            if not model.is_file() or not config.is_file():
                raise FileNotFoundError('A bundled AI model is missing. Reinstall Audio Switch AI.')
            return model.name, 'MDXC', name, str(model), str(config)
        def download_file_if_not_exists(self, url, output_path):
            if not Path(output_path).is_file():
                raise RuntimeError('Offline model data is missing from the app bundle.')

    if MODEL_CACHE and MODEL_CACHE[0] == name:
        sep = MODEL_CACHE[1]
        sep.output_dir = str(output)
        sep.model_instance.output_dir = str(output)
        return sep
    MODEL_CACHE = None
    gc.collect()
    import torch
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()
    status('Loading ' + {'vocals': 'vocal separation', 'lead': 'lead vocal', 'dereverb': 'reverb reduction'}[name] + ' model…', 0.08)
    sep = OfflineSeparator(
        log_level=logging.ERROR, model_file_dir=str(ROOT / 'Models' / name),
        output_dir=str(output), output_format='WAV', use_soundfile=True,
        normalization_threshold=1.0, amplification_threshold=0.0,
        mdxc_params={'segment_size': 256, 'override_model_segment_size': True, 'batch_size': 1, 'overlap': 2, 'pitch_shift': 0},
    )
    sep.load_model(name)
    MODEL_CACHE = (name, sep)
    return sep

def separate_roformer(source, folder, name):
    import numpy as np
    folder.mkdir(exist_ok=True)
    sep = separator_for(name, folder)
    from audio_separator.separator.architectures import mdxc_separator
    from tqdm import tqdm as base_tqdm
    class ProgressTqdm(base_tqdm):
        def update(self, amount=1):
            result = super().update(amount)
            if self.total:
                status('AI processing · ' + str(min(100, round(100*self.n/self.total))) + '%…', 0.2+0.55*min(1,self.n/self.total))
            return result
    mdxc_separator.tqdm = ProgressTqdm
    status({'vocals': 'Separating vocals and instrumental…', 'lead': 'Isolating the lead vocal…', 'dereverb': 'Reducing reverb…'}[name], 0.2)
    names = {'Vocals': 'vocals', 'Instrumental': 'instrumental', 'noreverb': 'dry', 'reverb': 'reverb', 'No Reverb': 'dry', 'Reverb': 'reverb'}
    paths = sep.separate(str(source), custom_output_names=names)
    found = {Path(p).stem.lower(): Path(p) if Path(p).is_absolute() else folder / p for p in paths}
    if name == 'dereverb':
        result = next((p for stem, p in found.items() if stem in ['dry', 'noreverb', 'no reverb']), None)
        if result is None:
            raise RuntimeError('The reverb model did not produce a dry output.')
        return {'dry': result}
    result = {}
    for label in ['vocals', 'instrumental']:
        path = next((p for stem, p in found.items() if stem == label), None)
        if path is None:
            raise RuntimeError('The vocal model did not produce the expected ' + label + ' output.')
        result[label] = path
    return result

def separate_stems(source, folder):
    """SCNet inference with bounded, overlapping windows and no online dependencies."""
    global MODEL_CACHE
    MODEL_CACHE = None
    gc.collect()
    import numpy as np
    import torch
    import yaml
    from vendor.scnet import SCNet
    folder.mkdir(exist_ok=True)
    data, rate = array_read(source)
    model_dir = ROOT / 'Models/stems'
    config = yaml.safe_load((model_dir / 'config.yaml').read_text())
    manifest = json.loads((model_dir / 'manifest.json').read_text())
    status('Loading four-stem separation model…', 0.08)
    model = SCNet(**config['model'])
    checkpoint = torch.load(model_dir / manifest['filename'], map_location='cpu', weights_only=True)
    if 'state' in checkpoint:
        checkpoint = checkpoint['state']
    if 'state_dict' in checkpoint:
        checkpoint = checkpoint['state_dict']
    model.load_state_dict(checkpoint, strict=True)
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    model.to(device).eval()
    torch.set_num_threads(min(8, os.cpu_count() or 4))
    samples = len(data)
    chunk = 44100 * 6
    hop = chunk // 2
    padded = np.pad(data, ((hop, hop + chunk), (0, 0)), mode='constant')
    result = np.zeros((4, padded.shape[0], 2), dtype=np.float32)
    weights = np.zeros(padded.shape[0], dtype=np.float32)
    window = np.hanning(chunk).astype('float32')
    starts = list(range(0, samples + hop, hop))
    with torch.inference_mode():
        for index, start in enumerate(starts):
            status(f'Separating drums, bass, vocals and other · {index + 1}/{len(starts)}…', 0.2 + 0.55 * index / len(starts))
            part = torch.from_numpy(padded[start:start + chunk].T.copy()).unsqueeze(0).to(device)
            prediction = model(part)[0].cpu().numpy().transpose(0, 2, 1)
            result[:, start:start + chunk] += prediction[..., :chunk, :] * window[None, :, None]
            weights[start:start + chunk] += window
    result = result[:, hop:hop + samples] / np.maximum(weights[hop:hop + samples], 1e-8)[None, :, None]
    paths = {}
    for index, label in enumerate(config['model']['sources']):
        path = folder / (label + '.wav')
        array_write(path, result[index], rate)
        paths[label] = path
    return paths

def ai_stage(source, temp, options):
    import numpy as np
    action = options.get('action', 'process')
    source_info, _ = probe(source)
    original_channels = int(source_info['channels'])
    if original_channels > 2:
        raise ValueError('AI processing supports mono or stereo. Convert this file to stereo first.')
    prepared = temp / 'ai-input.wav'
    decode(source, prepared, rate=44100, channels=2)
    base, rate = array_read(prepared)
    if action == 'stems':
        results = separate_stems(prepared, temp / 'stems')
    elif action in ['vocals', 'instrumental', 'lead']:
        separated = separate_roformer(prepared, temp / 'vocals', 'vocals')
        if action == 'lead':
            lead = separate_roformer(separated['vocals'], temp / 'lead', 'lead')
            results = {'lead-vocal': lead['vocals']}
        else:
            results = {action: separated[action]}
    else:
        results = {'processed': prepared}
    if options.get('dereverb'):
        strength = float(options.get('dereverbStrength', 0.7))
        for index, (label, path) in enumerate(list(results.items())):
            dry = separate_roformer(path, temp / f'dereverb-{index}', 'dereverb')['dry']
            wet_audio, _ = array_read(path)
            dry_audio, _ = array_read(dry)
            length = min(len(wet_audio), len(dry_audio))
            mixed = wet_audio[:length] * (1 - strength) + dry_audio[:length] * strength
            output = temp / (label + '-dry.wav')
            array_write(output, mixed, rate)
            results[label] = output
    if original_channels == 1:
        for label, path in list(results.items()):
            mono = temp / (label + '-mono.wav')
            data, rate = array_read(path)
            array_write(mono, data.mean(axis=1, keepdims=True), rate)
            results[label] = mono
    return results

def tempo_filters(value):
    filters = []
    while value < 0.5:
        filters.append('atempo=0.5'); value /= 0.5
    while value > 2:
        filters.append('atempo=2'); value /= 2
    if abs(value - 1) > 0.00001:
        filters.append(f'atempo={value:.8f}')
    return filters

def filters_for(options, rate, channel_count):
    filters = []
    channels = options.get('channels', 'preserve')
    if channels == 'mono':
        if channel_count == 2:
            filters.append('pan=mono|c0=0.5*c0+0.5*c1')
    elif channels in ['left', 'right', 'swap', 'split']:
        if channel_count != 2:
            raise ValueError('Left/right and swap operations require stereo input.')
        if channels in ['left', 'right']:
            filters.append('pan=mono|c0=c' + ('0' if channels == 'left' else '1'))
        elif channels == 'swap':
            filters.append('pan=stereo|c0=c1|c1=c0')
    hum = int(options.get('humHz', 0))
    if hum:
        for harmonic in range(1, 5):
            filters.append(f'equalizer=f={hum * harmonic}:t=q:w=25:g=-24')
    if options.get('rumbleHz', 0) > 0:
        filters.append('highpass=f=' + str(options['rumbleHz']))
    if options.get('declick'):
        filters.append('adeclick')
    if options.get('declip'):
        filters.append('adeclip')
    if options.get('noiseReduction'):
        strength = float(options.get('noiseStrength',12))
        mode = options.get('noiseMode','steady')
        if mode in ['voice','music']:
            model = 'bd.rnnn' if mode == 'voice' else 'mp.rnnn'
            mix = 1 - 10**(-strength/20)
            filters += ['aresample=48000', f'arnndn=m=Models/noise/{model}:mix={mix:.6f}', f'aresample={rate}']
        else:
            filters.append(f'afftdn=nr={strength}:nf=-50:tn=0')
    if options.get('deess'):
        filters.append('deesser=i=0.4:m=0.5:f=0.5')
    if options.get('trimSilence'):
        threshold = float(options.get('silenceDB', -50))
        # Trims only the ends; intentional pauses inside the performance remain.
        filters += [f'silenceremove=start_periods=1:start_duration=0.03:start_threshold={threshold}dB:start_silence=0.03:detection=rms', 'areverse', f'silenceremove=start_periods=1:start_duration=0.03:start_threshold={threshold}dB:start_silence=0.08:detection=rms', 'areverse']
    semitones = float(options.get('semitones', 0))
    factor = 2 ** (semitones / 12)
    if semitones:
        filters += [f'asetrate={rate}*{factor:.10f}', f'aresample={rate}']
    filters += tempo_filters(float(options.get('tempo', 1)) / factor)
    if options.get('reverse'):
        filters.append('areverse')
    if options.get('fadeIn', 0) > 0:
        filters.append('afade=t=in:d=' + str(options['fadeIn']))
    if options.get('fadeOut', 0) > 0:
        filters += ['areverse', 'afade=t=in:d=' + str(options['fadeOut']), 'areverse']
    if options.get('gainDB', 0):
        filters.append('volume=' + str(options['gainDB']) + 'dB')
    return filters

def measured_filter(source, filters, options):
    if options.get('normalize'):
        target = float(options.get('lufs', -16))
        measurement = filters + [f'loudnorm=I={target}:TP=-1:LRA=11:print_format=json']
        _, text = command([tool('ffmpeg'), '-hide_banner', '-nostdin', '-i', source, '-vn', '-af', ','.join(measurement), '-f', 'null', '-'])
        match = re.search(r'\{\s*"input_i"[\s\S]+?\}', text)
        if match:
            stats = json.loads(match.group())
            if all(math.isfinite(float(stats[k])) for k in ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']):
                return f'loudnorm=I={target}:TP=-1:LRA=11:measured_I={stats["input_i"]}:measured_TP={stats["input_tp"]}:measured_LRA={stats["input_lra"]}:measured_thresh={stats["input_thresh"]}:offset={stats["target_offset"]}:linear=true'
        return None # Silence remains silence.
    if options.get('peakNormalize'):
        _, text = command([tool('ffmpeg'), '-hide_banner', '-nostdin', '-i', source, '-vn', '-af', ','.join(filters + ['volumedetect']), '-f', 'null', '-'])
        match = re.search(r'max_volume:\s*([-\d.]+) dB', text)
        if match:
            return f'volume={float(options.get("peakDB", -1)) - float(match.group(1))}dB'
    return None

def output_encoding(options, source_stream, original):
    fmt = options.get('outputFormat', 'wav')
    if fmt == 'original':
        ext = original.suffix.lower().lstrip('.')
        fmt = {'wave': 'wav', 'aif': 'aiff', 'aifc': 'aiff', 'm4a': 'alac' if source_stream.get('codec_name') == 'alac' else 'aac'}.get(ext, ext)
        if fmt not in ['wav','aiff','flac','aac','alac','mp3','caf','ogg','opus']:
            fmt = 'wav'
    depth = int(options.get('bitDepth', 24))
    if depth == 0:
        depth = int(source_stream.get('bits_per_raw_sample') or source_stream.get('bits_per_sample') or 24)
        if depth not in [16,24,32,64]:
            depth = 24
    floating = options.get('bitDepth', 24) == 0 and source_stream.get('codec_name') in ['pcm_f32le','pcm_f32be','pcm_f64le','pcm_f64be']
    bits = min(32, depth)
    pcm = f'pcm_f{depth}le' if floating else f'pcm_s{bits}le'
    codecs = {
        'wav': ['-c:a', pcm, '-rf64', 'auto'],
        'aiff': ['-c:a', pcm[:-2] + 'be'],
        'caf': ['-c:a', pcm],
        'flac': ['-c:a', 'flac', '-compression_level', '8', '-sample_fmt', 's16' if bits == 16 else 's32', '-bits_per_raw_sample', '16' if bits == 16 else '24'],
        'aac': ['-c:a','aac','-b:a','256k','-movflags','+faststart'],
        'alac': ['-c:a','alac','-sample_fmt','s16p' if bits == 16 else 's32p'],
        'mp3': ['-c:a','libmp3lame','-b:a','320k'],
        'ogg': ['-c:a','vorbis','-strict','experimental','-q:a','6'],
        'opus': ['-c:a','libopus','-b:a','192k'],
    }
    if fmt not in codecs:
        raise ValueError('Choose a supported output format.')
    return fmt, 'm4a' if fmt in ['aac','alac'] else fmt, codecs[fmt]

def encode(source, dest, options, original_stream, original):
    stream, _ = probe(source)
    rate = int(options.get('sampleRate') or original_stream['sample_rate'])
    fmt, _, codec = output_encoding(options, original_stream, original)
    if fmt == 'mp3' and rate > 48000:
        raise ValueError('MP3 supports sample rates up to 48 kHz. Choose 48 kHz or a lossless format.')
    if fmt == 'opus' and rate != 48000:
        raise ValueError('Opus uses 48 kHz. Select 48 kHz for Opus output.')
    filters = filters_for(options, int(stream['sample_rate']), int(stream['channels']))
    extra = measured_filter(source, filters, options)
    if extra:
        filters.append(extra)
    args = ['-n', '-i', source, '-i', original, '-map', '0:a:0', '-map_metadata', '1', '-vn']
    if filters:
        args += ['-af', ','.join(filters)]
    if options.get('channels') in ['mono','left','right']:
        args += ['-ac','1']
    elif options.get('channels') == 'stereo':
        args += ['-ac','2']
    args += ['-ar', str(rate), *codec, dest]
    ffmpeg(*args)
    output, container = probe(dest)
    if int(output['sample_rate']) != rate:
        raise RuntimeError('The encoder could not produce the requested sample rate.')
    if duration(dest) < 0.001:
        raise ValueError('This operation produced empty audio. Try a lower silence threshold.')

def name_suffix(options, label, fmt):
    words = []
    action = options.get('action','process')
    if action in ['vocals','instrumental','lead','stems']:
        words.append(label)
    if options.get('dereverb'):
        words.append('dry')
    for flag, name in [('noiseReduction','denoised'), ('declick','declicked'), ('declip','declip'), ('deess','deessed'), ('trimSilence','trimmed'), ('reverse','reversed')]:
        if options.get(flag):
            words.append(name)
    if options.get('rumbleHz'):
        words.append('lowcut')
    if options.get('humHz'):
        words.append('dehum')
    if options.get('normalize'):
        words.append(f'{options.get("lufs",-16):g}LUFS')
    elif options.get('peakNormalize'):
        words.append('peak-normalized')
    if options.get('gainDB'):
        words.append(f'{options["gainDB"]:+g}dB')
    if options.get('channels','preserve') != 'preserve':
        words.append(label if options['channels'] == 'split' else options['channels'])
    if options.get('tempo',1) != 1:
        words.append(f'{options["tempo"]:g}x')
    if options.get('semitones'):
        words.append(f'{options["semitones"]:+g}st')
    if options.get('fadeIn') or options.get('fadeOut'):
        words.append('faded')
    if options.get('clipStart') or options.get('clipLength'):
        words.append('excerpt')
    if action in ['join','split']:
        words.append(label)
    if action == 'extract':
        words.append('audio')
    if options.get('sampleRate'):
        words.append(f'{options["sampleRate"]/1000:g}kHz')
    if options.get('outputFormat') != 'original':
        words.append(fmt)
    if options.get('bitDepth'):
        words.append(f'{options["bitDepth"]}bit')
    return '_'.join(words) or 'processed'

def publish(source, folder, stem, ext):
    stem = stem.encode('utf-8')[:220].decode('utf-8', 'ignore')
    check_cancelled()
    counter = 1
    while True:
        suffix = '' if counter == 1 else '_' + str(counter)
        target = folder / (stem + suffix + '.' + ext)
        try:
            if os.name == 'nt':
                # Windows rename fails if the destination exists; never replaces originals.
                os.rename(source, target)
            else:
                # Same-volume atomic no-clobber publication for portable regression tests.
                os.link(source, target)
                os.unlink(source)
            return target
        except FileExistsError:
            counter += 1
            continue

def inspect(source, temp):
    import numpy as np
    stream, container = probe(source)
    status('Measuring loudness and checking stereo…', 0.1)
    _, text = command([tool('ffmpeg'),'-hide_banner','-nostdin','-i',source,'-vn','-af','loudnorm=print_format=json','-f','null','-'])
    match = re.search(r'\{\s*"input_i"[\s\S]+?\}', text)
    loudness = json.loads(match.group()) if match else {}
    decoded = temp / 'analysis.wav'
    decode(source, decoded, rate=22050, length=120)
    data, rate = array_read(decoded)
    lines = [source.name, '', 'Codec: ' + stream.get('codec_long_name', stream.get('codec_name','Unknown')), f'Duration: {duration(source):.2f} seconds', f'Sample rate: {stream["sample_rate"]} Hz', f'Channels: {stream["channels"]}', 'Bit depth: ' + str(stream.get('bits_per_raw_sample') or stream.get('bits_per_sample') or 'encoded / not applicable')]
    lines += ['Integrated loudness: ' + str(loudness.get('input_i','unknown')) + ' LUFS', 'True peak: ' + str(loudness.get('input_tp','unknown')) + ' dBTP']
    if data.shape[1] == 2:
        left, right = data[:,0], data[:,1]
        if np.std(left)>1e-8 and np.std(right)>1e-8:
            correlation = float(np.corrcoef(left,right)[0,1])
            lines.append(f'Stereo correlation: {correlation:.3f}' + (' — check for cancellation in mono' if correlation < 0 else ''))
    mono = data.mean(axis=1)
    if np.max(np.abs(mono)) > 1e-5 and len(mono) >= rate * 3:
        status('Estimating tempo and musical key…', 0.5)
        import librosa
        tempo = librosa.feature.tempo(y=mono, sr=rate)
        chroma = librosa.feature.chroma_stft(y=mono, sr=rate).mean(axis=1)
        major = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        minor = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        scored = [(float(np.corrcoef(chroma,np.roll(profile,key))[0,1]),key,mode) for mode,profile in [('major',major),('minor',minor)] for key in range(12)]
        score,key,mode = max(scored)
        lines += [f'Tempo estimate: {float(tempo[0]):.1f} BPM', f'Key estimate: {["C","C♯","D","E♭","E","F","F♯","G","A♭","A","B♭","B"][key]} {mode}', '', 'Tempo and key are estimates from the first two minutes. Speech, free timing, key changes, and sparse recordings can give misleading results.']
    else:
        lines.append('Tempo/key: insufficient musical content to estimate.')
    return '\n'.join(lines)

def process_one(original, options, preview, preview_root):
    original = Path(original).resolve()
    original_stream, _ = probe(original)
    folder = preview_root if preview else original.parent
    with tempfile.TemporaryDirectory(prefix='.AudioSwitchAI-', dir=folder) as temp_name:
        temp = Path(temp_name)
        action = options.get('action', 'process')
        if action == 'inspect':
            return [], inspect(original, temp), None
        source = original
        if preview or options.get('clipStart',0) or options.get('clipLength',0):
            source = temp/'excerpt.wav'
            decode(original, source, start=float(options.get('clipStart',0)), length=15 if preview else float(options.get('clipLength',0)))
        if preview:
            reference = preview_root/'original.wav'
            ffmpeg('-n', '-i', source, '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', reference)
        else:
            reference = None
        use_ai = action in ['vocals','instrumental','lead','stems'] or options.get('dereverb')
        results = ai_stage(source,temp,options) if use_ai else {'processed': source}
        if action == 'split':
            seconds = float(options.get('splitSeconds',60))
            if seconds < 1:
                raise ValueError('Split length must be at least one second.')
            total = duration(source)
            split_source = next(iter(results.values()))
            results = {}
            for index in range(math.ceil(total / seconds)):
                start = index * seconds
                path = temp/f'part-{index+1:03}.wav'
                decode(split_source,path,start=start,length=seconds)
                results[f'part-{index+1:03}'] = path
        if options.get('channels') == 'split':
            split = {}
            for label,path in results.items():
                stream,_ = probe(path)
                if int(stream['channels']) != 2:
                    raise ValueError('Splitting left/right requires a stereo file.')
                for index,side in [(0,'left'),(1,'right')]:
                    p=temp/(label+'-'+side+'.wav')
                    ffmpeg('-n','-i',path,'-af',f'pan=mono|c0=c{index}','-c:a','pcm_f32le',p)
                    split[side if label=='processed' else label+'-'+side]=p
            results=split
        fmt,ext,_ = output_encoding(options,original_stream,original)
        staged=[]
        status('Applying cleanup and output settings…',0.8)
        for index,(label,path) in enumerate(results.items()):
            dest=temp/(f'final-{index}.'+ext)
            opts=dict(options)
            if opts.get('channels')=='split':
                opts['channels']='preserve'
            encode(path,dest,opts,original_stream,original)
            staged.append((dest, original.stem+'_'+name_suffix(options,label,fmt),ext))
        outputs=[]
        try:
            for path,stem,ext in staged:
                outputs.append(publish(path,folder,'preview_'+stem if preview else stem,ext))
        except BaseException:
            for path in outputs:
                path.unlink(missing_ok=True)
            raise
        return outputs, None, reference

def join_files(inputs,options):
    first=Path(inputs[0]).resolve()
    folder=first.parent
    stream,_=probe(first)
    with tempfile.TemporaryDirectory(prefix='.AudioSwitchAI-',dir=folder) as name:
        temp=Path(name)
        paths=[]
        for index,path in enumerate(inputs):
            status(f'Preparing file {index+1}/{len(inputs)} for joining…',index/max(1,len(inputs))*0.5)
            target=temp/f'{index:04}.wav'
            decode(Path(path),target,rate=int(stream['sample_rate']),channels=int(stream['channels']))
            paths.append(target)
        listing=temp/'inputs.txt'
        listing.write_text('\n'.join("file '"+p.name+"'" for p in paths))
        merged=temp/'joined.wav'
        ffmpeg('-n','-f','concat','-safe','1','-i',listing,'-c:a','pcm_f32le',merged)
        fmt,ext,_=output_encoding(options,stream,first)
        final=temp/('final.'+ext)
        source = merged
        if options.get('dereverb'):
            source = next(iter(ai_stage(merged,temp,options).values()))
        encode(source,final,options,stream,first)
        output=publish(final,folder,first.stem+'_joined_'+fmt,ext)
        return [output]

def validate_options(options):
    ranges = {'sampleRate': (0,384000), 'bitDepth': (0,32), 'dereverbStrength': (0,1), 'noiseStrength': (1,40), 'gainDB': (-60,30), 'tempo': (0.5,2), 'semitones': (-12,12), 'fadeIn': (0,600), 'fadeOut': (0,600), 'clipStart': (0,864000), 'clipLength': (0,864000), 'splitSeconds': (1,864000), 'silenceDB': (-90,-10), 'lufs': (-30,-9), 'peakDB': (-24,0)}
    for key,(minimum,maximum) in ranges.items():
        if key in options:
            value = float(options[key])
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f'{key} must be between {minimum:g} and {maximum:g}.')
    if options.get('sampleRate',0) and options['sampleRate'] < 8000:
        raise ValueError('Sample rate must be at least 8000 Hz, or Keep source rate.')
    if options.get('bitDepth',24) not in [0,16,24,32]:
        raise ValueError('Choose Auto, 16, 24, or 32 bit.')
    if options.get('channels','preserve') not in ['preserve','mono','stereo','left','right','swap','split']:
        raise ValueError('Choose a supported channel operation.')

def main():
    global ROOT,CURRENT_INDEX,CURRENT_TOTAL,CANCEL_FILE
    parser=argparse.ArgumentParser()
    parser.add_argument('--request',required=True)
    parser.add_argument('--resources')
    parser.add_argument('--cancel-file')
    args=parser.parse_args()
    if args.resources:
        ROOT=Path(args.resources).resolve()
    os.environ['PATH']=str(ROOT/'Tools/bin')+os.pathsep+os.environ.get('PATH','')
    os.environ['PYTORCH_ENABLE_MPS_FALLBACK']='1'
    os.environ['OMP_NUM_THREADS']='8'
    if args.cancel_file:
        CANCEL_FILE=Path(args.cancel_file)
        def monitor():
            global CANCELLED
            while not CANCELLED:
                if CANCEL_FILE.exists():
                    CANCELLED=True
                    child=CHILD
                    if child is not None and child.poll() is None:
                        try: child.terminate()
                        except OSError: pass
                    return
                threading.Event().wait(0.1)
        threading.Thread(target=monitor,daemon=True).start()
    job=json.loads(Path(args.request).read_text(encoding='utf-8'))
    inputs=job['inputs']
    options=job.get('options',{})
    validate_options(options)
    preview=bool(job.get('preview',False))
    preview_root=Path(job.get('previewDirectory') or Path(args.request).parent)
    CURRENT_TOTAL=len(inputs)
    failed=0
    try:
        if options.get('action')=='join':
            if preview:
                raise ValueError('Preview files individually before joining.')
            if len(inputs)<2:
                raise ValueError('Select at least two files to join, in the desired order.')
            paths=join_files(inputs,options)
            emit('result',index=0,outputs=[str(p) for p in paths])
        else:
            for index,path in enumerate(inputs[:1] if preview else inputs):
                CURRENT_INDEX=index
                try:
                    status('Reading '+Path(path).name+'…',0)
                    paths,report,reference=process_one(path,options,preview,preview_root)
                    emit('result',index=index,outputs=[str(p) for p in paths],report=report,reference=str(reference) if reference else None,preview=preview)
                except InterruptedError:
                    raise
                except BaseException as error:
                    failed+=1
                    traceback.print_exc(file=sys.stderr)
                    emit('error',index=index,message=str(error) or 'The audio operation did not produce the expected output.')
            emit('done',failed=failed,cancelled=False)
    except InterruptedError:
        emit('done',failed=failed,cancelled=True)
        return 130
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        emit('error',index=CURRENT_INDEX,message=str(error))
        return 1
    return 1 if failed else 0

if __name__=='__main__':
    sys.exit(main())
