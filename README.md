# Audio Switch AI — Windows test edition

Self-contained Windows x64 audio conversion, cleanup, and offline source separation.
The Windows interface provides the Mac edition's processing options using Qt for Python.
Explorer commands appear under **Show more options → Audio Switch AI** on Windows 11.
This initial edition uses CPU inference, with no separate runtime/model installation.

## Build and verify

Use a Windows x64 host with Python 3.12, `uv`, and Visual Studio's C++ build tools
available in a Developer Command Prompt:

```powershell
python build_windows.py
$res = 'build/Audio Switch AI Windows Test/Resources'
& "$res/Runtime/python.exe" -I -X utf8 engine_check.py --resources $res --ai
& "$res/Runtime/python.exe" -I -X utf8 ui_bridge_check.py --resources $res
```

The GitHub Actions workflow performs the build and these checks on a Windows runner,
then saves the installer ZIP, logs, and rendered UI as build artifacts. No audio or
user data is uploaded; checks generate their own audio fixtures. Models are fetched
by pinned repository revision and validated against SHA-256 manifests. The SCNet
checkpoint is loaded with a restricted weights loader and only model tensors retained.

The cross-assembly helper `prepare.py` is for the original macOS development workspace;
the portable Windows/GitHub build entry point is `build_windows.py`.

## Distribution

Extract the complete ZIP and run `Setup.exe`. It copies the private app to the current
user's Programs folder and registers shortcuts/context commands without administrator
access. The native Unicode launcher runs a private embedded Python and Qt interface.
No `.wav` default-app association is changed. Outputs publish with an atomic Windows
rename that refuses to replace an existing destination. Cancellation uses a local
request file and safe stage boundaries rather than abruptly terminating the worker.

The test build is unsigned; Windows may show an unknown-publisher prompt. Test the
installer and Explorer behavior on a real Windows PC using the included checklist.
Automated processing checks do not substitute for that real-world installation check.

## Licenses

App/worker source: GPL-3.0-or-later. Models retain their individual MIT, GPL-3.0,
Apache-2.0 and RNNoise notices. Qt/PySide6 and runtime dependencies retain their bundled
license files; FFmpeg is distributed as a separate GPL-enabled executable. See
`Licenses`, `ModelData`, and packaged dependency notices.
