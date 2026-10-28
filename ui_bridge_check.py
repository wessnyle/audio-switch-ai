"""Exercise the actual Qt-to-private-worker preview bridge on the target platform."""
import argparse,os,sys,tempfile
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--resources',required=True);args=parser.parse_args()
resources=Path(args.resources).resolve();sys.path.insert(0,str(resources/'UI'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import soundfile as sf
from app import QApplication,MainWindow,STYLE,QTimer

application=QApplication([]);application.setStyle('Fusion');application.setStyleSheet(STYLE)
if os.name=='nt':assert application.platformName()=='windows','Test the real Windows display backend'
with tempfile.TemporaryDirectory(prefix='AudioSwitchAI-ui-bridge-') as name:
    root=Path(name);path=root/'UI test café.wav';rate=48000;t=np.arange(rate)/rate
    sf.write(path,np.stack([.2*np.sin(2*np.pi*440*t)]*2,axis=1),rate,subtype='PCM_24')
    window=MainWindow([str(path)]);window.show();window.controls['gainDB'].setValue(-6)
    result={'done':False,'error':None}
    def start():
        try:
            assert window.run_button.isEnabled() and window.preview_button.isEnabled()
            window.run(True)
        except Exception as error:result['error']=str(error);application.quit()
    def check():
        if window.thread and not window.busy:
            try:
                assert window.preview_original and window.preview_result,window.message.text()
                data,_=sf.read(window.preview_result);assert abs(20*np.log10(abs(data).max()/.2)+6)<.05
                assert window.original_button.isEnabled() and window.result_button.isEnabled()
                window.grab().save(str(resources.parent/'windows-preview-ui.png'))
                window.controls['gainDB'].setValue(-3)
                assert window.preview_original is None and window.preview_result is None
                result['done']=True
            except Exception as error:result['error']=str(error)
            window.close();application.quit()
    timer=QTimer();timer.timeout.connect(check);timer.start(100)
    QTimer.singleShot(100,start);QTimer.singleShot(120000,application.quit)
    application.exec()
    assert result['done'] and not result['error'],result
print('PASS: native interface / worker bridge, real gain preview, playback controls, settings invalidate preview')
