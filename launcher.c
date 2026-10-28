#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

/* A native Unicode launcher; the private Python runtime is never installed globally. */
static void quote(wchar_t *out, const wchar_t *arg) {
    wcscat(out, L"\"");
    size_t slashes = 0;
    while (*arg) {
        if (*arg == L'\\') { slashes++; arg++; continue; }
        if (*arg == L'\"') {
            for (size_t i=0; i<2*slashes+1; i++) wcscat(out,L"\\");
        } else for (size_t i=0;i<slashes;i++) wcscat(out,L"\\");
        slashes=0;
        size_t n=wcslen(out); out[n]=*arg++; out[n+1]=0;
    }
    for(size_t i=0;i<2*slashes;i++) wcscat(out,L"\\");
    wcscat(out,L"\" ");
}
int WINAPI wWinMain(HINSTANCE a,HINSTANCE b,PWSTR ignored,int show) {
    wchar_t base[32768], runtime[32768], script[32768];
    GetModuleFileNameW(NULL,base,32768);
    wchar_t *name=wcsrchr(base,L'\\');
    int setup=name && !_wcsicmp(name+1,L"Setup.exe");
    if(name) *name=0;
    swprintf(runtime,32768,L"%ls\\Resources\\Runtime\\pythonw.exe",base);
    swprintf(script,32768,L"%ls\\Resources\\UI\\app.py",base);
    int argc=0; wchar_t **argv=CommandLineToArgvW(GetCommandLineW(),&argc);
    wchar_t *cmd=HeapAlloc(GetProcessHeap(),HEAP_ZERO_MEMORY,262144*sizeof(wchar_t));
    if(!cmd) return 1;
    quote(cmd,runtime); wcscat(cmd,L"-I "); quote(cmd,script);
    if(setup) wcscat(cmd,L"--install ");
    for(int i=1;i<argc;i++) quote(cmd,argv[i]);
    STARTUPINFOW si={0};si.cb=sizeof(si); PROCESS_INFORMATION pi={0};
    if(!CreateProcessW(runtime,cmd,NULL,NULL,FALSE,CREATE_NO_WINDOW,NULL,base,&si,&pi)) {
        MessageBoxW(NULL,L"Audio Switch AI could not start. Extract the entire ZIP first and keep the Resources folder beside this application. If it still fails, send your friend a screenshot of this message.",L"Audio Switch AI",MB_OK|MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);LocalFree(argv);HeapFree(GetProcessHeap(),0,cmd);
    return 0;
}
