# -*- coding: utf-8 -*-
"""팝업 버튼 선택 규칙 단위 시험 (ERPia 없이 돈다).

사용자 규칙: 확인만 있으면 '확인', 예/아니오면 '아니오'.
"""
import io
import sys

sys.path.insert(0, r"D:\AX\RPA")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import run_routine as rr  # noqa: E402

fails = []


class FakeBtn:
    def __init__(self, t):
        self.t = t

    def window_text(self):
        return self.t


def pick(names):
    b = rr.pick_popup_button([FakeBtn(n) for n in names])
    return None if b is None else b.window_text()


CASES = [
    (["확인(O)"], "확인(O)", "확인만 있는 팝업(필독 안내)"),
    (["확인"], "확인", "확인만 있는 팝업"),
    (["예(Y)", "아니오(N)"], "아니오(N)", "예/아니오 팝업 -> 아니오"),
    (["예", "아니오"], "아니오", "예/아니오(단축키 없음) -> 아니오"),
    (["아니요(N)", "예(Y)"], "아니요(N)", "'아니요' 표기도 잡는다"),
    (["확인", "취소"], "확인", "확인/취소 -> 확인 (취소 아님)"),
    (["닫기"], None, "모르는 버튼만 있으면 건드리지 않는다"),
    ([], None, "버튼이 없으면 None"),
    (["예(Y)"], "예(Y)", "예만 있으면 예"),
]

for names, want, what in CASES:
    got = pick(names)
    ok = got == want
    print(("PASS " if ok else "FAIL ") + f"{what}: {names} -> {got!r} (기대 {want!r})")
    if not ok:
        fails.append(what)

print("\n실패:", fails if fails else "없음")
sys.exit(1 if fails else 0)
