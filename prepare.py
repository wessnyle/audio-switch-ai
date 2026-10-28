"""Cross-assemble the Windows x64 test distribution on macOS; no Mac binaries included."""
from concurrent.futures import ThreadPoolExecutor
import hashlib, json, shutil, subprocess, tarfile, urllib.request, zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
CACHE = BASE/'work/windows-build/cache'
PACKAGE = BASE/'work/windows-build/package/Audio Switch AI Windows Test'
RES = PACKAGE/'Resources'
CACHE.mkdir(parents=True,exist_ok=True)

def download(name,url):
    path=CACHE/name
    if not path.exists():
        temp=path.with_suffix('.download')
        with urllib.request.urlopen(url,timeout=90) as r,temp.open('wb') as f:
            shutil.copyfileobj(r,f,1024*1024)
        temp.rename(path)
    print(name,hashlib.sha256(path.read_bytes()).hexdigest(),flush=True)
    return path

def main():
    urls=[
        ('python-3.12.10-embed-amd64.zip','https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'),
        ('zig-0.15.2.tar.xz','https://ziglang.org/download/0.15.2/zig-aarch64-macos-0.15.2.tar.xz'),
        ('ffmpeg-win64.zip','https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'),
    ]
    with ThreadPoolExecutor(max_workers=3) as pool: files=list(pool.map(lambda pair:download(*pair),urls))
    assert hashlib.sha256(files[1].read_bytes()).hexdigest()=='3cc2bab367e185cdfb27501c4b30b1b0653c28d9f73df8dc91488e66ece5fa6b'
    RES.mkdir(parents=True,exist_ok=True)
    runtime=RES/'Runtime';runtime.mkdir(exist_ok=True)
    with zipfile.ZipFile(files[0]) as z:z.extractall(runtime)
    (runtime/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\nimport site\n')
    site=runtime/'Lib/site-packages'
    shutil.copytree(BASE/'work/windows-build/site-packages',site,dirs_exist_ok=True)
    # uv-generated console wrappers target the build host and are not used by the app.
    shutil.rmtree(site/'bin',ignore_errors=True)
    # Make the redistributable C++ runtime available to every private native package.
    for dll in (site/'PySide6').glob('msvcp*.dll'):shutil.copy2(dll,runtime/dll.name)
    tools=RES/'Tools/bin';tools.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(files[2]) as z:
        for name in z.namelist():
            leaf=Path(name).name
            if leaf in ['ffmpeg.exe','ffprobe.exe']:
                (tools/leaf).write_bytes(z.read(name))
            elif leaf.lower().startswith('license'):
                (RES/'Tools'/leaf).write_bytes(z.read(name))
    shutil.copytree(BASE/'work/ai-models',RES/'Models',dirs_exist_ok=True)
    shutil.copytree(BASE/'work/AudioSwitchAI/Licenses',RES/'Licenses',dirs_exist_ok=True)
    zigdir=CACHE/'zig-aarch64-macos-0.15.2'
    if not zigdir.exists():
        with tarfile.open(files[1]) as t:t.extractall(CACHE,filter='data')
    target=PACKAGE/'Audio Switch AI.exe'
    subprocess.run([str(zigdir/'zig'),'cc','-target','x86_64-windows-gnu','-Os','-municode','-Wl,--subsystem,windows',str(Path(__file__).with_name('launcher.c')),'-lshell32','-o',str(target)],check=True)
    shutil.copy2(target,PACKAGE/'Setup.exe')
    provenance={'build':'Windows x64 test 2.1.0-beta.1','downloads':[{'url':u,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for (_,u),p in zip(urls,files)]}
    (RES/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print('Prepared',PACKAGE,flush=True)

if __name__=='__main__':main()
