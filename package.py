"""Preserve source and notices, then ZIP the self-contained distribution."""
from pathlib import Path
import hashlib,shutil,zipfile
source=Path(__file__).resolve().parent
build=source/'build';package=build/'Audio Switch AI Windows Test'
shutil.copytree(source,package/'Source',ignore=shutil.ignore_patterns('build','__pycache__','*.pyc','.git'),dirs_exist_ok=True)
archive=build/'Audio Switch AI Windows Test.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
    for p in sorted(package.rglob('*')):
        if p.is_file():z.write(p,p.relative_to(build))
h=hashlib.sha256()
with archive.open('rb') as f:
    for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
(build/'SHA256.txt').write_text(h.hexdigest()+'  '+archive.name+'\n')
print('Packaged',archive,archive.stat().st_size,'bytes')
