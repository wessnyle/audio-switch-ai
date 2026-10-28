"""Per-user Explorer commands and shortcuts. No admin access or file associations changed."""
import base64, json, os, subprocess, sys
from pathlib import Path
from core import QUICK_ACTIONS, VERSION

APP_NAME='Audio Switch AI'
EXTENSIONS=['.wav','.wave','.aif','.aiff','.aifc','.flac','.m4a','.mp3','.caf','.ogg','.opus','.wma','.aac','.mp4','.mov','.mkv','.avi','.webm']

def registry_commands(exe):
    # Separate commands keep Windows' Unicode argument handling, without cmd.exe or PowerShell.
    return [(title,f'"{exe}" --quick-action {mode} -- "%1"') for title,mode in QUICK_ACTIONS]

def install_context(exe):
    import winreg
    keys=[]
    for ext in EXTENSIONS:
        base=rf'Software\Classes\SystemFileAssociations\{ext}\shell\AudioSwitchAI'
        keys.append(base)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base) as k:
            for name,value in [('MUIVerb',APP_NAME),('Icon',str(exe)),('SubCommands','')]:
                winreg.SetValueEx(k,name,0,winreg.REG_SZ,value)
        for index,(title,command) in enumerate(registry_commands(exe)):
            sub=base+rf'\shell\{index:02}'
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,sub) as k:
                winreg.SetValueEx(k,'MUIVerb',0,winreg.REG_SZ,title)
                winreg.SetValueEx(k,'MultiSelectModel',0,winreg.REG_SZ,'Single')
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,sub+r'\command') as k:
                winreg.SetValueEx(k,'',0,winreg.REG_SZ,command)
    notify_shell()
    return keys

def remove_tree(path):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_READ|winreg.KEY_WRITE) as k:
            children=[]
            while True:
                try:children.append(winreg.EnumKey(k,len(children)))
                except OSError:break
        for child in children:remove_tree(path+'\\'+child)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER,path)
    except FileNotFoundError:pass

def remove_context(exe):
    import winreg
    for ext in EXTENSIONS:
        base=rf'Software\Classes\SystemFileAssociations\{ext}\shell\AudioSwitchAI'
        # Only remove entries owned by this installed copy.
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,base) as k:
                if winreg.QueryValueEx(k,'Icon')[0]!=str(exe):continue
            remove_tree(base)
        except FileNotFoundError:pass
    notify_shell()

def notify_shell():
    import ctypes
    ctypes.windll.shell32.SHChangeNotify(0x08000000,0,None,None)

def ps_literal(value):return "'"+str(value).replace("'","''")+"'"

def powershell(script,wait=True):
    system=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    exe=system/'System32/WindowsPowerShell/v1.0/powershell.exe'
    args=[str(exe),'-NoProfile','-NonInteractive','-EncodedCommand',base64.b64encode(script.encode('utf-16le')).decode('ascii')]
    if wait:
        subprocess.run(args,check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    else:subprocess.Popen(args,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)

def shortcut_paths():
    import ctypes
    # Respect Windows' redirected / OneDrive Desktop rather than assuming USERPROFILE\Desktop.
    desktop=ctypes.create_unicode_buffer(32768)
    result=ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,desktop)
    if result!=0:raise OSError('Windows could not locate the Desktop folder.')
    return [Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Audio Switch AI.lnk',Path(desktop.value)/'Audio Switch AI.lnk']

def register_install(root):
    import winreg
    exe=root/'Audio Switch AI.exe'
    install_context(exe)
    script="$ErrorActionPreference='Stop';$w=New-Object -ComObject WScript.Shell;"
    for path in shortcut_paths():
        path.parent.mkdir(parents=True,exist_ok=True)
        script+=f'$s=$w.CreateShortcut({ps_literal(path)});$s.TargetPath={ps_literal(exe)};$s.WorkingDirectory={ps_literal(root)};$s.IconLocation={ps_literal(exe)};$s.Save();'
    powershell(script)
    key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioSwitchAI'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,key) as k:
        for name,value in [('DisplayName','Audio Switch AI (Windows test)'),('DisplayVersion',VERSION),('InstallLocation',str(root)),('UninstallString',f'"{exe}" --uninstall'),('DisplayIcon',str(exe))]:
            winreg.SetValueEx(k,name,0,winreg.REG_SZ,value)
        for name in ['NoModify','NoRepair']:winreg.SetValueEx(k,name,0,winreg.REG_DWORD,1)
    (root/'installation.json').write_text(json.dumps({'application':'Audio Switch AI','version':VERSION,'root':str(root)}),encoding='utf-8')

def unregister_install(root):
    remove_context(root/'Audio Switch AI.exe')
    for path in shortcut_paths():path.unlink(missing_ok=True)
    remove_tree(r'Software\Microsoft\Windows\CurrentVersion\Uninstall\AudioSwitchAI')

def schedule_remove(root):
    marker=root/'installation.json'
    if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')).get('root')!=str(root):
        raise ValueError('This folder has no matching installation record. Remove it manually after closing the app.')
    # Wait for this process to exit before removing its own private runtime.
    script=f"$ErrorActionPreference='Stop';Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue;Start-Sleep -Seconds 2;Remove-Item -LiteralPath {ps_literal(root)} -Recurse -Force;"
    powershell(script,wait=False)
