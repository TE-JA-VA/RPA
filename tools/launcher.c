/* 조각 방식의 시작 파일 (설계 2026-11-11 조각 빌드 4절). tools/build_release.py 의 build_launchers 가 zig 로 만든다.
 *
 * 자기 폴더 D 에서 D\python\pythonNNN.dll 을 올려 같은 프로세스 안에서 Py_Main 을 돈다:
 *     <exe> -s D\app\_start.py <사용자 인자...>
 * 같은 프로세스여야 한다 - '실행 중' 판정이 프로세스 이름을 보고, 옵저버의 관리자 재실행이 exe 자리를 쓴다.
 * Python.h 는 쓰지 않는다 (내장 Python 에 헤더가 없다). 못 켜면 한 줄 안내와 종료 코드 2.
 */
#include <windows.h>
#include <wchar.h>
#include <stdlib.h>

#ifndef PYVER
#define PYVER 314
#endif
#define WSTR2(x) L## #x
#define WSTR(x) WSTR2(x)
#define N 32768

typedef int (*py_main_fn)(int, wchar_t **);

static wchar_t dir[N], home[N], dll[N], script[N], text[N + 128];
static char utf8[(N + 128) * 3];

static int has_check(int argc, wchar_t **argv) {
    for (int i = 1; i < argc; i++)
        if (wcscmp(argv[i], L"--check") == 0) return 1;
    return 0;
}

static int fail(const wchar_t *missing, int argc, wchar_t **argv) {
    _snwprintf(text, N + 127, L"오토파일럿을 시작하지 못했습니다. 다시 설치하여 주십시오. (%ls)\n", missing);
    HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    DWORD done = 0;
    int n = WideCharToMultiByte(CP_UTF8, 0, text, -1, utf8, sizeof(utf8), NULL, NULL);
    int wrote = err && err != INVALID_HANDLE_VALUE && n > 1 && WriteFile(err, utf8, (DWORD)(n - 1), &done, NULL);
#ifdef WINDOWED
    if (!wrote && !has_check(argc, argv)) MessageBoxW(NULL, text, L"오토파일럿", MB_ICONERROR);
#else
    (void)wrote; (void)argc; (void)argv;
#endif
    return 2;
}

static int run(int argc, wchar_t **argv) {
    DWORD len = GetModuleFileNameW(NULL, dir, N);
    if (len == 0 || len >= N) return fail(L"실행 파일 경로", argc, argv);
    static wchar_t exe[N];
    wcscpy(exe, dir);
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (!slash) return fail(exe, argc, argv);
    *slash = 0;
    _snwprintf(home, N - 1, L"%ls\\python", dir);
    _snwprintf(dll, N - 1, L"%ls\\python" WSTR(PYVER) L".dll", home);
    _snwprintf(script, N - 1, L"%ls\\app\\_start.py", dir);
    if (GetFileAttributesW(script) == INVALID_FILE_ATTRIBUTES) return fail(script, argc, argv);
    /* C 런타임의 환경 사본까지 바꾼다 (_wputenv_s) - Python 은 _wgetenv 로 읽어 SetEnvironmentVariableW 만으로는 못 본다.
       PC 에 잡혀 있는 파이썬 환경 변수가 우리 라이브러리(lib)를 가리거나 끝난 뒤 대화형으로 남게 하지 않는다 (빈 값 = 지움) */
    _wputenv_s(L"PYTHONHOME", home);
    _wputenv_s(L"PYTHONPATH", L"");
    _wputenv_s(L"PYTHONSTARTUP", L"");
    _wputenv_s(L"PYTHONINSPECT", L"");
    HMODULE py = LoadLibraryExW(dll, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!py) return fail(dll, argc, argv);
    py_main_fn py_main = (py_main_fn)(void *)GetProcAddress(py, "Py_Main");
    if (!py_main) return fail(dll, argc, argv);
    wchar_t **args = (wchar_t **)HeapAlloc(GetProcessHeap(), 0, sizeof(wchar_t *) * (size_t)(argc + 3));
    if (!args) return fail(L"메모리", argc, argv);
    args[0] = exe;
    args[1] = L"-s";
    args[2] = script;
    for (int i = 1; i < argc; i++) args[i + 2] = argv[i];
    args[argc + 2] = NULL;
    return py_main(argc + 2, args);
}

#ifdef WINDOWED
int WINAPI wWinMain(HINSTANCE a, HINSTANCE b, PWSTR c, int d) {
    (void)a; (void)b; (void)c; (void)d;
    return run(__argc, __wargv);
}
#else
int wmain(int argc, wchar_t **argv) {
    return run(argc, argv);
}
#endif
