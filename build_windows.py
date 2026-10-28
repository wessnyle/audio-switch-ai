"""Build the identical Windows x64 package on a Windows runner using pinned inputs."""
from concurrent.futures import ThreadPoolExecutor
import argparse,hashlib,json,os,shutil,subprocess,sys,urllib.request,zipfile
from pathlib import Path

SOURCE=Path(__file__).resolve().parent
BUILD=SOURCE/'build'
PACKAGE=BUILD/'Audio Switch AI Windows Test'
RES=PACKAGE/'Resources'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def download(url,path,expected=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or (expected and digest(path)!=expected):
        temp=path.with_suffix(path.suffix+'.download')
        with urllib.request.urlopen(url,timeout=120) as r,temp.open('wb') as f:shutil.copyfileobj(r,f,1024*1024)
        temp.replace(path)
    if expected and digest(path)!=expected:raise ValueError('SHA-256 mismatch: '+str(path))
    return path

def strip_checkpoint(source,target):
    import torch
    class IgnoredTrainingState:pass
    def empty_dictionary(*args):return {}
    allowed=[(IgnoredTrainingState,'bitsandbytes.optim.adamw.AdamW8bit'),(IgnoredTrainingState,'torch.optim.lr_scheduler.ReduceLROnPlateau'),(empty_dictionary,'collections.defaultdict'),dict]
    with torch.serialization.safe_globals(allowed):checkpoint=torch.load(source,map_location='cpu',weights_only=True)
    state=checkpoint['model_state_dict']
    if not isinstance(state,dict) or not all(isinstance(v,torch.Tensor) for v in state.values()):raise ValueError('Invalid stem checkpoint')
    torch.save(state,target)

def prepare_models():
    shutil.copytree(SOURCE/'ModelData',RES/'Models',dirs_exist_ok=True)
    def prepare(folder):
        manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
        if folder.name=='noise':
            for file in manifest['files']:
                download(f"https://raw.githubusercontent.com/richardpl/arnndn-models/{manifest['revision']}/{file['filename']}",folder/file['filename'],file['sha256'])
        elif folder.name=='stems':
            original=BUILD/'cache'/manifest['original_filename']
            download(f"{manifest['repository']}/resolve/{manifest['revision']}/{manifest['original_filename']}",original,manifest['original_sha256'])
            target=folder/'weights.pt'
            strip_checkpoint(original,target)
            manifest.update(sha256=digest(target),bytes=target.stat().st_size)
            (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        else:
            download(f"{manifest['repository']}/resolve/{manifest['revision']}/{manifest['filename']}",folder/manifest['filename'],manifest['sha256'])
        print('Verified model:',folder.name,flush=True)
    folders=[p for p in (RES/'Models').iterdir() if p.is_dir()]
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(prepare,folders))

def main():
    if os.name!='nt':raise RuntimeError('Run this build script on Windows x64.')
    BUILD.mkdir(exist_ok=True);RES.mkdir(parents=True,exist_ok=True)
    inputs=json.loads((SOURCE/'binary-inputs.json').read_text())
    runtime=RES/'Runtime';runtime.mkdir(exist_ok=True)
    for entry in inputs:
        archive=download(entry['url'],BUILD/'cache'/entry['filename'],entry['sha256'])
        with zipfile.ZipFile(archive) as z:
            if entry['name']=='python':z.extractall(runtime)
            else:
                tools=RES/'Tools/bin';tools.mkdir(parents=True,exist_ok=True)
                for name in z.namelist():
                    leaf=Path(name).name
                    if leaf in ['ffmpeg.exe','ffprobe.exe']:(tools/leaf).write_bytes(z.read(name))
                    elif leaf.lower().startswith('license'):(RES/'Tools'/leaf).write_bytes(z.read(name))
    (runtime/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n',encoding='utf-8')
    site=runtime/'Lib/site-packages'
    subprocess.run(['uv','pip','install','--target',str(site),'--python-version','3.12','--only-binary',':all:','--torch-backend','cpu','-r',str(SOURCE/'requirements-windows.lock')],check=True)
    for dll in (site/'PySide6').glob('msvcp*.dll'):shutil.copy2(dll,runtime/dll.name)
    for folder in ['Backend','UI','Licenses']:shutil.copytree(SOURCE/folder,RES/folder,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (RES/'Tests').mkdir(exist_ok=True);shutil.copy2(SOURCE/'engine_check.py',RES/'Tests/engine_check.py')
    # Weight stripping runs with the newly assembled Windows Python and its dependencies.
    subprocess.run([str(runtime/'python.exe'),'-I','-X','utf8',str(SOURCE/'build_windows.py'),'--models-only'],check=True)
    exe=PACKAGE/'Audio Switch AI.exe'
    subprocess.run(['cl','/nologo','/O2','/MT','/DUNICODE','/D_UNICODE',str(SOURCE/'launcher.c'),'/Fe:'+str(exe),'/Fo:'+str(BUILD/'launcher.obj'),'/link','/SUBSYSTEM:WINDOWS','shell32.lib','user32.lib'],check=True)
    shutil.copy2(exe,PACKAGE/'Setup.exe')
    shutil.copy2(SOURCE/'START HERE.txt',PACKAGE/'START HERE.txt')
    shutil.copy2(SOURCE/'FRIEND TEST CHECKLIST.txt',PACKAGE/'FRIEND TEST CHECKLIST.txt')
    if (SOURCE/'icon.png').exists():shutil.copy2(SOURCE/'icon.png',RES/'icon.png')
    shutil.copy2(SOURCE/'requirements-windows.lock',RES/'requirements-windows.lock')
    (RES/'provenance.json').write_text(json.dumps({'build':'Windows x64 test 2.1.0-beta.1','downloads':inputs},indent=2),encoding='utf-8')
    print('Windows package ready:',PACKAGE,flush=True)

if __name__=='__main__':
    if '--models-only' in sys.argv:prepare_models()
    else:main()
