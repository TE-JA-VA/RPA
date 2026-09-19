# -*- coding: utf-8 -*-
"""ERPia 대신 팝업을 띄우는 가짜 프로그램 (시험용).

사용: fake_popup_app.py <시나리오> <남아있을 초>
  시나리오 (쉼표로 이어서 차례대로 띄움):
    error   개체 참조 오류 (확인만)            -> 별도 창
    fail    정상매출처리 실패 (확인만)          -> 별도 창
    yesno   예/아니요 질문                      -> 별도 창
    notice  Cafe24 필독 안내 (확인만)           -> 별도 창
    overlay 메인 창 안에 오류 문구 + 확인 버튼  -> 자식 창
첫 줄에 메인 창 hwnd 를 찍고, 메시지 상자마다 눌린 버튼 번호(1=확인, 6=예, 7=아니요)를 찍는다.
"""
import ctypes
import sys
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
MB_OK, MB_YESNO, MB_ICONERROR, MB_ICONQUESTION = 0x0, 0x4, 0x10, 0x20

TEXT = {
    "error": ("개체 참조가 개체의 인스턴스로 설정되지 않았습니다.", "오류", MB_OK | MB_ICONERROR),
    "fail": ("정상매출처리 실패", "알림", MB_OK),
    "yesno": ("재수집하시겠습니까?", "확인", MB_YESNO | MB_ICONQUESTION),
    "notice": ("** Cafe24 필독사항 입니다. ** 로그인 실패의 경우 재수집해주세요.", "필독", MB_OK),
}

scenario = sys.argv[1].split(",")
linger = float(sys.argv[2]) if len(sys.argv) > 2 else 5

main = user32.CreateWindowExW(0, "STATIC", "fake erpia main", WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                              200, 200, 700, 450, None, None, None, None)
print(int(main), flush=True)

msg = wintypes.MSG()


def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.02)


pump(1.5)
for step in scenario:
    if step == "overlay":
        user32.CreateWindowExW(0, "STATIC", TEXT["error"][0], WS_CHILD | WS_VISIBLE,
                               20, 20, 600, 40, main, None, None, None)
        user32.CreateWindowExW(0, "BUTTON", "확인", WS_CHILD | WS_VISIBLE,
                               20, 80, 120, 40, main, None, None, None)
        print("overlay shown", flush=True)
        pump(0.5)
        continue
    text, title, flags = TEXT[step]
    rc = user32.MessageBoxW(main, text, title, flags)
    print(f"{step} rc={rc}", flush=True)
    pump(0.3)

pump(linger)
print("exit", flush=True)
