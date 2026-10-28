"""Audio Switch AI: self-contained Windows desktop interface, GPL-3.0-or-later."""
from __future__ import annotations
import argparse, datetime, json, logging, os, shutil, subprocess, sys, tempfile, traceback, uuid, zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
RES=HERE.parent
ROOT=RES.parent
DATA=Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'Audio Switch AI'
LOGS=DATA/'Logs'
LOGS.mkdir(parents=True,exist_ok=True)
logging.basicConfig(filename=LOGS/'application.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')

try:
    from PySide6.QtCore import Qt, QThread, Signal, QTimer, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,
        QLabel,QPushButton,QComboBox,QDoubleSpinBox,QCheckBox,QGroupBox,QScrollArea,QTabWidget,
        QListWidget,QListWidgetItem,QAbstractItemView,QProgressBar,QPlainTextEdit,QFileDialog,
        QMessageBox,QInputDialog,QDialog,QSplitter)
    from core import DEFAULTS,ACTIONS,PRESETS,VERSION,preset,quick_settings,preview_options
except Exception:
    logging.exception('Startup failed')
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'Audio Switch AI could not load its interface. Startup details are in:\n'+str(LOGS/'application.log'),'Audio Switch AI',0x10)
    raise

STYLE='''
QMainWindow,QDialog {background:#f5f5fa;color:#222239;}
QWidget {font-family:"Segoe UI";font-size:13px;}
QGroupBox {background:white;border:1px solid #e0e1ed;border-radius:9px;margin-top:16px;padding:14px 12px 10px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:12px;padding:0 5px;}
QPushButton {background:white;border:1px solid #d9d9e7;border-radius:6px;padding:7px 12px;color:#303049;}
QPushButton:hover {border-color:#7665d6;background:#f3f0ff;}
QPushButton:disabled {color:#92929f;background:#ededf2;}
QPushButton[primary="true"] {background:#6955d8;color:white;border:1px solid #6955d8;font-weight:600;}
QPushButton[primary="true"]:disabled {background:#b9b1e5;border-color:#b9b1e5;}
QComboBox,QDoubleSpinBox {background:white;border:1px solid #d9d9e7;border-radius:5px;padding:5px;min-height:19px;}
QComboBox QAbstractItemView {background:white;color:#222239;selection-background-color:#e9e3ff;}
QListWidget,QPlainTextEdit {background:white;border:1px solid #e0e1ed;border-radius:8px;padding:6px;}
QListWidget::item {padding:9px 5px;border-bottom:1px solid #f0f0f5;}
QListWidget::item:selected {background:#eae5ff;color:#292042;border-radius:5px;}
QTabWidget::pane {border:0;}
QTabBar::tab {padding:9px 16px;background:#eaeaf2;border-radius:5px;margin:0 4px 6px 0;}
QTabBar::tab:selected {background:#e7e0ff;color:#5140a5;}
QProgressBar {border:0;background:#e1e1ec;border-radius:4px;max-height:9px;}
QProgressBar::chunk {background:#7662df;border-radius:4px;}
QScrollArea {border:0;background:transparent;}
QCheckBox {spacing:7px;font-weight:400;}
'''

def python_exe():return RES/'Runtime/python.exe' if os.name=='nt' else Path(sys.executable)

def environment():
    env=dict(os.environ)
    env.update(PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1',OMP_NUM_THREADS='8',
        NUMBA_CACHE_DIR=str(DATA/'Cache/numba'),PYTORCH_ENABLE_MPS_FALLBACK='1')
    if os.name=='nt':
        system=Path(os.environ.get('SystemRoot',r'C:\Windows'))
        env['PATH']=os.pathsep.join(map(str,[RES/'Tools/bin',RES/'Runtime',system/'System32',system]))
    else:env['PATH']=str(RES/'Tools/bin')+os.pathsep+env.get('PATH','')
    return env

class Worker(QThread):
    event=Signal(dict)
    completed=Signal(int,str)
    def __init__(self,job,folder,diagnostics=False):
        super().__init__();self.job=job;self.folder=folder;self.diagnostics=diagnostics
        self.cancel=folder/'cancel';self.log=LOGS/(folder.name+'.log')
    def run(self):
        try:
            args=[str(python_exe()),'-I','-X','utf8']
            if self.diagnostics:args += [str(RES/'Tests/engine_check.py'),'--resources',str(RES)]
            else:
                request=self.folder/'request.json';request.write_text(json.dumps(self.job,ensure_ascii=False),encoding='utf-8')
                args += [str(RES/'Backend/worker.py'),'--resources',str(RES),'--request',str(request),'--cancel-file',str(self.cancel)]
            with self.log.open('w',encoding='utf-8') as log:
                process=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=log,encoding='utf-8',errors='replace',env=environment(),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                for line in process.stdout:
                    log.write(line);log.flush()
                    try:self.event.emit(json.loads(line))
                    except (ValueError,TypeError):pass
                code=process.wait()
            self.completed.emit(code,str(self.log))
        except Exception:
            logging.exception('Could not run worker')
            self.completed.emit(1,traceback.format_exc())

class CopyInstall(QThread):
    completed=Signal(bool,str)
    progress=Signal(str)
    def __init__(self,target):super().__init__();self.target=target
    def run(self):
        staging=self.target.parent/('Audio Switch AI.installing-'+uuid.uuid4().hex)
        try:
            from windows_integration import register_install
            if self.target.resolve()!=ROOT.resolve():
                if self.target.exists():raise RuntimeError('Audio Switch AI is already installed. Close it and uninstall the previous Windows test build first from Settings > Apps > Installed apps.')
                self.target.parent.mkdir(parents=True,exist_ok=True)
                staging.mkdir()
                self.progress.emit('Copying bundled runtime and AI models…')
                shutil.copytree(RES,staging/'Resources')
                shutil.copy2(ROOT/'Audio Switch AI.exe',staging/'Audio Switch AI.exe')
                if (ROOT/'START HERE.txt').exists():shutil.copy2(ROOT/'START HERE.txt',staging/'START HERE.txt')
                staging.rename(self.target)
            self.progress.emit('Adding shortcuts and right-click commands…')
            register_install(self.target)
            self.completed.emit(True,str(self.target))
        except Exception as error:
            logging.exception('Installation failed')
            shutil.rmtree(staging,ignore_errors=True)
            self.completed.emit(False,str(error)+'\n\nIf the app was copied successfully, open it from the install folder and click Install right-click actions. You can also run the extracted copy directly.')

class InstallDialog(QDialog):
    def __init__(self):
        super().__init__();self.setWindowTitle('Install Audio Switch AI · Windows test');self.resize(540,300)
        layout=QVBoxLayout(self)
        title=QLabel('Audio Switch AI');title.setStyleSheet('font-size:27px;font-weight:700;color:#5140a5;');layout.addWidget(title)
        self.target=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'Programs/Audio Switch AI'
        label=QLabel('Windows x64 test build '+VERSION+'\n\nIncludes all processing tools and AI models.\nNo separate Python/AI installation or administrator access needed.\n\nInstall location:\n'+str(self.target));label.setWordWrap(True);layout.addWidget(label)
        self.status=QLabel('Right-click commands appear under Show more options on Windows 11.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.button=QPushButton('Install Audio Switch AI');self.button.setProperty('primary',True);self.button.clicked.connect(self.install);layout.addWidget(self.button)
        self.thread=None
    def install(self):
        self.button.setEnabled(False);self.thread=CopyInstall(self.target)
        self.thread.progress.connect(self.status.setText);self.thread.completed.connect(self.done_copy);self.thread.start()
    def done_copy(self,ok,detail):
        self.thread.wait()
        if ok:
            QMessageBox.information(self,'Installed','Audio Switch AI is installed.\n\nRight-click an audio file > Show more options > Audio Switch AI.\n\nThe app will now open.')
            os.startfile(str(self.target/'Audio Switch AI.exe'));self.accept()
        else:QMessageBox.critical(self,'Installation needs attention',detail);self.button.setEnabled(True)
    def closeEvent(self,event):
        if self.thread and self.thread.isRunning():event.ignore()
        else:event.accept()

class MainWindow(QMainWindow):
    def __init__(self,files=None,mode=None):
        super().__init__();self.setWindowTitle('Audio Switch AI · Windows test');self.resize(1100,830);self.setMinimumSize(900,680);self.setAcceptDrops(True)
        self.controls={};self.paths=[];self.row_status={};self.outputs=[];self.thread=None;self.busy=False;self.loading=False
        self.preview_folder=None;self.preview_original=None;self.preview_result=None;self.player=None;self.close_pending=False;self.failed=0;self.is_preview=False;self.is_diagnostics=False
        try:self.saved=json.loads((DATA/'presets.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):self.saved={}
        self.build();self.load_settings(quick_settings(mode));self.add_files(files or [])
    def button(self,text,fn,primary=False):
        b=QPushButton(text);b.setProperty('primary',primary);b.clicked.connect(fn);return b
    def combo(self,key,items):
        c=QComboBox()
        for label,value in items:c.addItem(label,value)
        c.currentIndexChanged.connect(self.changed);self.controls[key]=c;return c
    def number(self,key,minimum,maximum,step=1,decimals=1,suffix=''):
        c=QDoubleSpinBox();c.setRange(minimum,maximum);c.setSingleStep(step);c.setDecimals(decimals);c.setSuffix(suffix)
        c.valueChanged.connect(self.changed);self.controls[key]=c;return c
    def check(self,key,label):
        c=QCheckBox(label);c.toggled.connect(self.changed);self.controls[key]=c;return c
    def group(self,title):
        g=QGroupBox(title);form=QFormLayout(g);form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow);form.setVerticalSpacing(9);return g,form
    def scroll(self,widget):
        s=QScrollArea();s.setWidgetResizable(True);s.setWidget(widget);return s
    def build(self):
        central=QWidget();self.setCentralWidget(central);outer=QVBoxLayout(central);outer.setContentsMargins(22,18,22,18);outer.setSpacing(12)
        heading=QHBoxLayout();title=QLabel('Audio Switch AI');title.setStyleSheet('font-size:27px;font-weight:700;color:#5140a5;');heading.addWidget(title)
        heading.addStretch();tag=QLabel('OFFLINE  ·  WINDOWS TEST');tag.setStyleSheet('font-size:11px;font-weight:600;color:#75718f;');heading.addWidget(tag);outer.addLayout(heading)
        subtitle=QLabel('Convert, clean up, and separate audio. New copies save beside your originals.');subtitle.setStyleSheet('color:#696579;');outer.addWidget(subtitle)
        split=QSplitter(Qt.Horizontal);outer.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,10,0)
        label=QLabel('FILES');label.setStyleSheet('font-weight:600;color:#75718f;');ll.addWidget(label)
        self.files=QListWidget();self.files.setSelectionMode(QAbstractItemView.ExtendedSelection);self.files.setMinimumWidth(260);ll.addWidget(self.files,1)
        row=QHBoxLayout();self.add_button=self.button('Add files…',self.choose_files);self.clear_button=self.button('Clear',self.clear_files)
        for b in [self.add_button,self.clear_button]:row.addWidget(b)
        ll.addLayout(row)
        row=QHBoxLayout();self.up=self.button('Move up',lambda:self.move(-1));self.down=self.button('Move down',lambda:self.move(1));self.remove_button=self.button('Remove',self.remove_files)
        for b in [self.up,self.down,self.remove_button]:row.addWidget(b)
        ll.addLayout(row)
        presets,form=self.group('Presets');self.presets=QComboBox();self.presets.addItems(list(PRESETS)+sorted(self.saved));form.addRow(self.presets)
        pbuttons=QHBoxLayout();pbuttons.addWidget(self.button('Apply',self.apply_preset));pbuttons.addWidget(self.button('Save current…',self.save_preset));form.addRow(pbuttons);ll.addWidget(presets)
        self.integration=self.button('Install right-click actions',self.install_context);ll.addWidget(self.integration)
        self.remove_integration=self.button('Remove right-click actions',self.remove_context);ll.addWidget(self.remove_integration)
        self.diagnostics=self.button('Check audio engine',self.run_diagnostics);ll.addWidget(self.diagnostics)
        ll.addWidget(self.button('Export diagnostic logs…',self.export_logs))
        hint=QLabel('Windows 11: right-click →\nShow more options → Audio Switch AI.\n\nAI separation may take several minutes\non a CPU. Start with Preview 15s.');hint.setStyleSheet('color:#767286;font-size:12px;');hint.setWordWrap(True);ll.addWidget(hint)
        split.addWidget(left)
        right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(8,0,0,0)
        rl.addWidget(QLabel('ACTION'));rl.addWidget(self.combo('action',ACTIONS));self.tabs=QTabWidget();rl.addWidget(self.tabs,1)
        process=QWidget();pl=QVBoxLayout(process);pl.setContentsMargins(0,0,0,0)
        g,f=self.group('AI cleanup')
        f.addRow(self.check('dereverb','Reduce reverb'),self.number('dereverbStrength',0,1,.1,2))
        f.addRow(self.check('noiseReduction','Reduce noise'),self.combo('noiseMode',[('Voice / vocal AI','voice'),('General audio AI','music'),('Steady hiss','steady')]))
        f.addRow('Noise reduction amount',self.number('noiseStrength',1,40,1,0,' dB'))
        note=QLabel('AI works with mono/stereo. Lead-only extraction is experimental.');note.setWordWrap(True);note.setStyleSheet('color:#817a91;font-size:11px;');f.addRow(note);pl.addWidget(g)
        g,f=self.group('Repair & filtering');f.addRow(self.check('declick','Reduce clicks'),self.check('declip','Approximate clipping repair'));f.addRow(self.check('deess','Reduce sibilance'))
        f.addRow('Hum removal',self.combo('humHz',[('Off',0),('50 Hz',50),('60 Hz',60)]));f.addRow('Low-cut filter',self.combo('rumbleHz',[('Off',0),('40 Hz',40),('80 Hz',80),('120 Hz',120)]));pl.addWidget(g)
        g,f=self.group('Editing');f.addRow('Channels',self.combo('channels',[(a,b) for a,b in [('Keep source','preserve'),('Mono','mono'),('Stereo','stereo'),('Left only','left'),('Right only','right'),('Swap L/R','swap'),('Split L/R files','split')]]))
        f.addRow(self.check('trimSilence','Trim silence at ends'),self.number('silenceDB',-90,-10,1,0,' dB'))
        f.addRow('Fade in',self.number('fadeIn',0,600,.1,2,' s'));f.addRow('Fade out',self.number('fadeOut',0,600,.1,2,' s'))
        f.addRow('Tempo (pitch preserved)',self.number('tempo',.5,2,.05,2,' ×'));f.addRow('Pitch (duration preserved)',self.number('semitones',-12,12,1,1,' st'));f.addRow(self.check('reverse','Reverse audio'))
        f.addRow('Excerpt / preview start',self.number('clipStart',0,864000,1,2,' s'));f.addRow('Excerpt length (0 = whole file)',self.number('clipLength',0,864000,1,2,' s'));f.addRow('Length per split part',self.number('splitSeconds',1,864000,1,2,' s'));pl.addWidget(g);pl.addStretch()
        self.tabs.addTab(self.scroll(process),'Processing')
        output=QWidget();ol=QVBoxLayout(output);ol.setContentsMargins(0,0,0,0)
        g,f=self.group('File settings');f.addRow('Format',self.combo('outputFormat',[('WAV','wav'),('AIFF','aiff'),('FLAC','flac'),('M4A · AAC','aac'),('Apple Lossless','alac'),('MP3','mp3'),('CAF','caf'),('OGG Vorbis','ogg'),('Opus','opus'),('Keep source format','original')]))
        f.addRow('Sample rate',self.combo('sampleRate',[('Keep source rate',0)]+[(f'{n/1000:g} kHz',n) for n in [8000,11025,16000,22050,24000,32000,44100,48000,88200,96000,176400,192000]]))
        f.addRow('Bit depth',self.combo('bitDepth',[('Auto',0),('16 bit',16),('24 bit',24),('32 bit',32)]));ol.addWidget(g)
        g,f=self.group('Level');f.addRow('Gain',self.number('gainDB',-60,30,.5,1,' dB'))
        f.addRow(self.check('normalize','Normalize loudness'),self.number('lufs',-30,-9,1,1,' LUFS'));f.addRow(self.check('peakNormalize','Normalize peak'),self.number('peakDB',-24,0,.5,1,' dBFS'));ol.addWidget(g)
        helptext=QLabel('New files save beside each original, with the changes added to the name. Existing files are protected; duplicate names get _2, _3, and so on.\n\nOpus requires 48 kHz. MP3 supports up to 48 kHz. AI separation and reverb processing use 44.1 kHz internally.\n\nPreview uses a 16-bit WAV so it can play directly. Final files use these output settings.');helptext.setWordWrap(True);helptext.setStyleSheet('color:#777185;');ol.addWidget(helptext);ol.addStretch();self.tabs.addTab(self.scroll(output),'Output')
        results=QWidget();results_layout=QVBoxLayout(results);results_layout.setContentsMargins(0,0,0,0);self.results=QPlainTextEdit();self.results.setReadOnly(True);results_layout.addWidget(self.results);self.tabs.addTab(results,'Results')
        preview=QHBoxLayout();self.preview_button=self.button('Preview 15s',lambda:self.run(True));self.original_button=self.button('Play original',lambda:self.play(True));self.result_button=self.button('Play result',lambda:self.play(False));self.stop_audio=self.button('Stop audio',self.stop_playback)
        for b in [self.preview_button,self.original_button,self.result_button,self.stop_audio]:preview.addWidget(b)
        rl.addLayout(preview);split.addWidget(right);split.setStretchFactor(0,0);split.setStretchFactor(1,1);split.setSizes([320,740])
        self.progress=QProgressBar();self.progress.setRange(0,1000);self.progress.setTextVisible(False);outer.addWidget(self.progress)
        footer=QHBoxLayout();self.message=QLabel('Add files or drop them here. Originals stay untouched.');self.message.setWordWrap(True);footer.addWidget(self.message,1)
        self.show_button=self.button('Show copies',self.show_copies);self.stop_button=self.button('Stop',self.stop);self.run_button=self.button('Process files',lambda:self.run(False),True)
        for b in [self.show_button,self.stop_button,self.run_button]:footer.addWidget(b)
        outer.addLayout(footer);self.update_buttons()
    def settings(self):
        values={}
        for key,w in self.controls.items():
            values[key]=w.currentData() if isinstance(w,QComboBox) else w.isChecked() if isinstance(w,QCheckBox) else w.value()
        for key in ['sampleRate','bitDepth','humHz','rumbleHz']:values[key]=int(values[key])
        return values
    def load_settings(self,values):
        self.loading=True
        for key,w in self.controls.items():
            value=values.get(key,DEFAULTS[key])
            if isinstance(w,QComboBox):w.setCurrentIndex(max(0,w.findData(value)))
            elif isinstance(w,QCheckBox):w.setChecked(bool(value))
            else:w.setValue(float(value))
        self.loading=False;self.clear_preview();self.update_buttons()
    def changed(self,*unused):
        if self.loading:return
        # Loudness normalization and peak normalization are mutually exclusive.
        sender=self.sender()
        if sender is self.controls.get('normalize') and sender.isChecked():self.controls['peakNormalize'].setChecked(False)
        elif sender is self.controls.get('peakNormalize') and sender.isChecked():self.controls['normalize'].setChecked(False)
        self.clear_preview();self.update_buttons()
    def update_buttons(self):
        if not hasattr(self,'run_button'):return
        s=self.settings();can=bool(self.paths) and not self.busy and (s['action']!='join' or len(self.paths)>1)
        self.run_button.setEnabled(can);self.preview_button.setEnabled(can and s['action'] not in ['inspect','join','split'] and s['channels']!='split')
        self.original_button.setEnabled(bool(self.preview_original) and not self.busy);self.result_button.setEnabled(bool(self.preview_result) and not self.busy)
        self.stop_button.setEnabled(self.busy and not self.is_diagnostics);self.show_button.setEnabled(bool(self.outputs))
        for w in [self.add_button,self.clear_button,self.up,self.down,self.remove_button,self.presets,self.integration,self.remove_integration,self.diagnostics,*self.controls.values()]:w.setEnabled(not self.busy)
    def choose_files(self):
        names,_=QFileDialog.getOpenFileNames(self,'Choose audio or video files','','Audio / video (*.wav *.wave *.aif *.aiff *.aifc *.flac *.m4a *.mp3 *.caf *.ogg *.opus *.wma *.aac *.mp4 *.mov *.mkv *.avi *.webm);;All files (*)')
        self.add_files(names)
    def add_files(self,names):
        if self.busy:return
        for name in names:
            path=Path(name).resolve()
            if path.is_file() and str(path).casefold() not in [str(p).casefold() for p in self.paths]:self.paths.append(path)
        self.refresh_files();self.update_buttons()
    def refresh_files(self):
        self.files.clear()
        for p in self.paths:
            item=QListWidgetItem(p.name+'\n'+self.row_status.get(str(p),'Ready'));item.setToolTip(str(p));self.files.addItem(item)
    def clear_files(self):
        if self.busy:return
        self.paths=[];self.row_status={};self.outputs=[];self.results.clear();self.clear_preview();self.refresh_files();self.update_buttons()
    def remove_files(self):
        if self.busy:return
        rows={self.files.row(i) for i in self.files.selectedItems()};self.paths=[p for i,p in enumerate(self.paths) if i not in rows];self.clear_preview();self.refresh_files();self.update_buttons()
    def move(self,direction):
        if self.busy:return
        index=self.files.currentRow();other=index+direction
        if 0<=index<len(self.paths) and 0<=other<len(self.paths):
            self.paths[index],self.paths[other]=self.paths[other],self.paths[index];self.refresh_files();self.files.setCurrentRow(other);self.clear_preview()
    def dragEnterEvent(self,event):
        if not self.busy and event.mimeData().hasUrls():event.acceptProposedAction()
    def dropEvent(self,event):self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])
    def apply_preset(self):
        if not self.busy:self.load_settings(preset(self.presets.currentText(),self.saved))
    def save_preset(self):
        if self.busy:return
        name,ok=QInputDialog.getText(self,'Save preset','Preset name:')
        name=name.strip()
        if ok and name:
            if name in PRESETS:QMessageBox.information(self,'Choose another name','That name belongs to a built-in preset.');return
            self.saved[name]=self.settings();(DATA/'presets.json').write_text(json.dumps(self.saved,indent=2),encoding='utf-8')
            if self.presets.findText(name)<0:self.presets.addItem(name)
            self.presets.setCurrentText(name);self.message.setText('Preset saved: '+name)
    def install_context(self):
        if os.name!='nt':self.message.setText('Explorer integration is available on Windows.');return
        try:
            from windows_integration import install_context
            install_context(ROOT/'Audio Switch AI.exe');self.message.setText('Installed. Right-click an audio file → Show more options → Audio Switch AI.')
        except Exception as error:QMessageBox.critical(self,'Could not install actions',str(error))
    def remove_context(self):
        if os.name!='nt':return
        try:
            from windows_integration import remove_context
            remove_context(ROOT/'Audio Switch AI.exe');self.message.setText('Removed this copy’s right-click actions. Your audio files are unchanged.')
        except Exception as error:QMessageBox.critical(self,'Could not remove actions',str(error))
    def run(self,preview=False):
        if self.busy or not self.paths:return
        self.clear_preview();self.failed=0;self.is_preview=preview;self.is_diagnostics=False;self.busy=True
        folder=Path(tempfile.mkdtemp(prefix='AudioSwitchAI-job-'))
        if preview:self.preview_folder=folder
        else:self.outputs=[];self.row_status={str(p):'Waiting' for p in self.paths};self.refresh_files()
        s=self.settings();s=preview_options(s) if preview else s
        job={'inputs':[str(p) for p in self.paths],'options':s,'preview':preview,'previewDirectory':str(folder)}
        self.progress.setValue(0);self.message.setText('Preparing a preview…' if preview else 'Starting local processing…')
        self.thread=Worker(job,folder);self.thread.event.connect(self.handle);self.thread.completed.connect(self.finished);self.thread.start();self.update_buttons()
    def run_diagnostics(self):
        if self.busy:return
        self.clear_preview();self.busy=True;self.is_preview=False;self.is_diagnostics=True;self.failed=0
        folder=Path(tempfile.mkdtemp(prefix='AudioSwitchAI-check-'))
        self.results.clear();self.tabs.setCurrentIndex(2);self.message.setText('Checking bundled Windows engine…');self.progress.setRange(0,0)
        self.thread=Worker({},folder,True);self.thread.event.connect(self.handle);self.thread.completed.connect(self.finished);self.thread.start();self.update_buttons()
    def handle(self,event):
        kind=event.get('type');index=event.get('index',0)
        if kind=='progress':
            self.message.setText(event.get('message','Processing…'))
            if 'progress' in event:self.progress.setValue(round(event['progress']*1000))
            if not self.is_preview and not self.is_diagnostics and index<len(self.paths):self.row_status[str(self.paths[index])]='Processing…';self.refresh_files()
        elif kind=='result':
            paths=[Path(p) for p in event.get('outputs',[])]
            if self.is_preview:
                self.preview_original=Path(event['reference']) if event.get('reference') else None
                self.preview_result=paths[0] if paths else None
            else:
                self.outputs+=paths
                if index<len(self.paths):self.row_status[str(self.paths[index])]='Done';self.refresh_files()
            if event.get('report'):self.results.appendPlainText(event['report']+'\n');self.tabs.setCurrentIndex(2)
            for path in paths:self.results.appendPlainText('Saved: '+str(path))
        elif kind=='error':
            self.failed+=1;self.results.appendPlainText('Error: '+event.get('message','Unknown failure'));self.tabs.setCurrentIndex(2)
            if not self.is_preview and not self.is_diagnostics and index<len(self.paths):self.row_status[str(self.paths[index])]='Failed';self.refresh_files()
        elif kind=='check':self.results.appendPlainText(event.get('message',''))
    def finished(self,code,log):
        self.thread.wait();cancelled=self.thread.cancel.exists();self.busy=False;self.progress.setRange(0,1000);self.progress.setValue(1000 if not cancelled else 0)
        if self.is_diagnostics:self.message.setText('Engine checks passed. Try a short audio preview next.' if code==0 else 'Engine check failed. Export diagnostic logs to share the details.')
        elif cancelled:
            self.message.setText('Stopped. Completed copies remain beside the originals.')
            for key,value in self.row_status.items():
                if value in ['Waiting','Processing…']:self.row_status[key]='Stopped'
            self.refresh_files()
        elif code!=0:self.message.setText('Some processing failed. See Results and export diagnostic logs if needed.');self.results.appendPlainText('Diagnostic log: '+log);self.tabs.setCurrentIndex(2)
        elif self.is_preview:self.message.setText('Preview ready. Play original and result to compare.')
        elif self.settings()['action']=='inspect':self.message.setText('Inspection complete. Read the Results tab.')
        else:self.message.setText(f'{len(self.outputs)} copies saved beside the originals.')
        if not self.is_preview:shutil.rmtree(self.thread.folder,ignore_errors=True)
        self.update_buttons()
        if self.close_pending:self.close()
    def stop(self):
        if self.thread and self.busy and not self.is_diagnostics:
            self.thread.cancel.touch();self.message.setText('Stopping safely after the current model step…');self.stop_button.setEnabled(False)
    def stop_playback(self):
        if os.name=='nt':
            import winsound
            winsound.PlaySound(None,0)
        elif self.player and self.player.poll() is None:self.player.terminate()
        self.player=None
    def clear_preview(self):
        self.stop_playback();self.preview_original=None;self.preview_result=None
        if self.preview_folder:shutil.rmtree(self.preview_folder,ignore_errors=True)
        self.preview_folder=None
    def play(self,original):
        path=self.preview_original if original else self.preview_result
        if not path:return
        try:
            self.stop_playback()
            if os.name=='nt':
                import winsound
                winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
            elif sys.platform=='darwin':self.player=subprocess.Popen(['/usr/bin/afplay',str(path)])
        except Exception as error:self.message.setText('Could not play preview: '+str(error))
    def show_copies(self):
        if not self.outputs:return
        if os.name=='nt':subprocess.Popen(['explorer.exe','/select,',str(self.outputs[0])])
        else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.outputs[0].parent)))
    def export_logs(self):
        name,_=QFileDialog.getSaveFileName(self,'Save diagnostic logs',str(Path.home()/'Desktop/Audio Switch AI diagnostics.zip'),'ZIP archive (*.zip)')
        if not name:return
        try:
            import platform
            with zipfile.ZipFile(name,'w',zipfile.ZIP_DEFLATED) as z:
                for p in LOGS.glob('*.log'):z.write(p,'Logs/'+p.name)
                z.writestr('System.txt',f'Audio Switch AI {VERSION}\n{platform.platform()}\n{platform.machine()}\nLogs can contain input filenames and paths; no audio files are included.\n')
            self.message.setText('Diagnostic ZIP saved. It contains logs, not your audio.')
        except Exception as error:QMessageBox.critical(self,'Could not export logs',str(error))
    def closeEvent(self,event):
        if self.busy:
            if self.is_diagnostics:QMessageBox.information(self,'Check running','Please wait for the engine check to finish.');event.ignore();return
            if self.close_pending or QMessageBox.question(self,'Stop processing?','Stop safely and close after the current model step?')==QMessageBox.Yes:self.close_pending=True;self.stop()
            event.ignore();return
        self.clear_preview();event.accept()

def uninstall():
    if os.name!='nt':return
    if QMessageBox.question(None,'Uninstall Audio Switch AI','Remove this Windows app, its shortcuts, and its right-click commands?\n\nYour audio files and saved presets stay in place.')!=QMessageBox.Yes:return
    try:
        from windows_integration import unregister_install,schedule_remove
        # Validate ownership before changing any registration.
        record=ROOT/'installation.json'
        if not record.is_file() or json.loads(record.read_text(encoding='utf-8')).get('root')!=str(ROOT):raise ValueError('Run the uninstaller from the installed app, or remove the extracted folder manually.')
        unregister_install(ROOT);schedule_remove(ROOT)
        QMessageBox.information(None,'Uninstalling','The app folder will be removed after this window closes. Your audio files are preserved.')
    except Exception as error:QMessageBox.critical(None,'Uninstall needs attention',str(error))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true');parser.add_argument('--uninstall',action='store_true');parser.add_argument('--quick-action');parser.add_argument('--ui-smoke');parser.add_argument('files',nargs='*');args=parser.parse_args()
    app=QApplication(sys.argv);app.setStyle('Fusion');app.setStyleSheet(STYLE);app.setApplicationName('Audio Switch AI')
    if (RES/'icon.png').exists():app.setWindowIcon(QIcon(str(RES/'icon.png')))
    def excepthook(kind,value,tb):
        logging.error('Unhandled UI exception',exc_info=(kind,value,tb))
        QMessageBox.critical(None,'Audio Switch AI',str(value)+'\n\nDetails were saved in diagnostic logs.')
    sys.excepthook=excepthook
    if args.install:
        if os.name!='nt':raise RuntimeError('The Windows installer must run on Windows.')
        dialog=InstallDialog();dialog.exec();return 0
    if args.uninstall:uninstall();return 0
    window=MainWindow(args.files,args.quick_action);window.show()
    if args.ui_smoke:
        def smoke():
            assert window.settings()==quick_settings(args.quick_action)
            assert len(window.controls)==len(DEFAULTS)
            window.grab().save(args.ui_smoke)
            Path(args.ui_smoke).with_suffix('.json').write_text(json.dumps({'settings':window.settings(),'files':[str(p) for p in window.paths]},ensure_ascii=False),encoding='utf-8')
            app.quit()
        QTimer.singleShot(500,smoke)
    return app.exec()

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:logging.exception('Fatal startup error');raise
