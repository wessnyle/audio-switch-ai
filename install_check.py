"""Verify the actual native launcher and per-user installer on an isolated Windows runner."""
import argparse,hashlib,json,os,shutil,subprocess,sys,tempfile,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--resources',required=True);args=parser.parse_args()
res=Path(args.resources).resolve();package=res.parent
if os.name!='nt':raise RuntimeError('Windows installation checks must run on Windows.')
sys.path.insert(0,str(res/'UI'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from app import QApplication,CopyInstall
from windows_integration import shortcut_paths,unregister_install,EXTENSIONS,registry_commands
import winreg
application=QApplication([])
assert application.platformName()=='windows','Test the real Windows display backend'
with tempfile.TemporaryDirectory(prefix='AudioSwitchAI-install-test-') as name:
    root=Path(name)
    # Exercise Unicode, apostrophes, ampersands and a trailing-space-free path through C quoting.
    audio=root/"Friend's & café test.wav";audio.write_bytes(b'test fixture')
    screenshot=root/'launcher.png'
    subprocess.run([str(package/'Audio Switch AI.exe'),'--quick-action','dereverb','--ui-smoke',str(screenshot),'--',str(audio)],check=True,timeout=30)
    for attempt in range(120):
        if screenshot.with_suffix('.json').exists():break
        time.sleep(.5)
    assert screenshot.exists(),'Native launcher did not render the interface'
    result=json.loads(screenshot.with_suffix('.json').read_text(encoding='utf-8'))
    assert result['settings']['dereverb'] and result['files']==[str(audio.resolve())],result
    shutil.copy2(screenshot,package/'windows-native-launcher.png')
    print('PASS: native Windows launcher, private runtime, Unicode arguments and quick-action dispatch',flush=True)
    target=root/'Installed Audio Switch AI'
    result={}
    installer=CopyInstall(target)
    installer.completed.connect(lambda ok,detail:result.update(ok=ok,detail=detail))
    installer.run()
    assert result.get('ok'),result
    assert (target/'installation.json').exists()
    assert (target/'Resources/Runtime/pythonw.exe').exists()
    assert all(p.exists() for p in shortcut_paths())
    key=r'Software\Classes\SystemFileAssociations\.wav\shell\AudioSwitchAI\shell\00\command'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as k:command=winreg.QueryValueEx(k,'')[0]
    assert command==registry_commands(target/'Audio Switch AI.exe')[0][1]
    print('PASS: real installer staging/copy, installed runtime, Desktop/Start Menu shortcuts and Explorer registration',flush=True)
    unregister_install(target)
    assert not any(p.exists() for p in shortcut_paths())
    try:winreg.OpenKey(winreg.HKEY_CURRENT_USER,key)
    except FileNotFoundError:pass
    else:raise AssertionError('Explorer registration not removed')
    shutil.rmtree(target)
    print('PASS: uninstaller registration cleanup; installed directory can be removed',flush=True)
