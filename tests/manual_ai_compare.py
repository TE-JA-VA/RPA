# -*- coding: utf-8 -*-
"""ACTOR AI 도움 손 시험 - 실제 AI(Haiku 5.5·Sonnet 5.5)로 가짜 쇼핑몰 화면 R1~R10 을 돌려 고름이 맞는지·시간·토큰을 견준다.
돈이 든다 (수십 번 호출, 1달러 안쪽). 일괄 시험에 넣지 말 것. 화면은 가짜 쇼핑몰뿐이라 고객 정보는 나가지 않는다 (창은 뜨지 않는다).

키는 이 창의 환경 변수로만 넘긴다 - 파일·로그·화면 어디에도 찍지 않는다:
    $env:ANTHROPIC_API_KEY = "sk-ant-..."     (PowerShell, 이 창에서만)
    .venv\\Scripts\\python.exe tests\\manual_ai_compare.py            (두 모델)
    .venv\\Scripts\\python.exe tests\\manual_ai_compare.py haiku      (한 모델만 - haiku 또는 sonnet)
    Remove-Item Env:ANTHROPIC_API_KEY
결과는 .superpowers\\sdd\\2026-11-16-actor-ai-rescue-1-replay\\manual_ai.md (한 모델만이면 manual_ai_haiku.md 처럼) 에 표로 남는다.
"""
import os
import re
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import ai_rescue as ai  # noqa: E402
import test_ai_rescue as t  # noqa: E402

MODELS = tuple(m for m in ("claude-haiku-5-5", "claude-sonnet-5-5") if len(sys.argv) < 2 or sys.argv[1] in m)
OUT = os.path.join(os.path.dirname(HERE), ".superpowers", "sdd", "2026-11-16-actor-ai-rescue-1-replay",
                   "manual_ai.md" if len(MODELS) > 1 else f"manual_ai_{sys.argv[1]}.md")

# (이름, 서버 모드, 바라는 결과) - 바라는 결과: (성공해야 하나, 눌려야 하는 것들, 눌리면 안 되는 것들)
CASES = [
    ("R1 단추 글 바뀜", dict(btn="엑셀 다운로드"), (True, ["excel", "ok"], [])),
    ("R2 공지 레이어", dict(layer="notice"), (True, ["close", "excel", "ok"], [])),
    ("R3 약관 동의 레이어", dict(layer="terms"), (False, [], ["agree"])),
    ("R4 안내 레이어 [확인]", dict(layer="info"), (True, ["info", "excel", "ok"], [])),
    ("R5 신청 레이어 [확인]", dict(layer="apply"), (False, [], ["apply"])),
    ("R6 완료 화면 신청 레이어 [예]", dict(done_layer="apply_yes"), (False, ["excel"], ["apply"])),
    ("R7 [주문취소] 옆 바뀐 단추", dict(btn="엑셀 다운로드", cancel=True), (True, ["excel", "ok"], ["cancel"])),
    ("R8 안 닫히는 공지", dict(layer="stuck"), (False, [], ["excel"])),
    ("R9 눌러도 아무 일 없음", dict(btn="엑셀 다운로드", dead=True), (False, [], ["ok"])),
    ("R10 메뉴·단추 둘 다 바뀜", dict(menu="주문 관리 바로가기", btn="엑셀 다운로드"), (True, ["excel", "ok"], [])),
]
TOKENS = re.compile(r"토큰 (\d+)\+(\d+)")


def main():
    if not MODELS:
        print("모델 이름은 haiku 또는 sonnet 입니다.")
        return 2
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ANTHROPIC_API_KEY 가 없습니다. 이 창에서 $env:ANTHROPIC_API_KEY = \"sk-ant-...\" 를 먼저 넣으세요.")
        return 2
    srv = t.ThreadingHTTPServer(("127.0.0.1", 0), t.Shop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    rows = []
    try:
        recd = t.record(base)
        for model in MODELS:
            for name, mode, (want_ok, must, never) in CASES:
                t.set_mode(**mode)
                answers = []
                claude = ai.Claude(key, model=model, log=answers.append)
                t0 = time.time()
                ok, r, fail, logs = t.replay(recd, claude)
                took = time.time() - t0
                hits = list(t.HITS)
                right = ok == want_ok and all(h in hits for h in must) and not any(h in hits for h in never)
                ins = sum(int(m.group(1)) for a in answers for m in [TOKENS.search(a)] if m)
                outs = sum(int(m.group(2)) for a in answers for m in [TOKENS.search(a)] if m)
                said = " / ".join(a.split("AI 답: ", 1)[-1].split(" (토큰")[0] for a in answers)
                rows.append((model, name, "맞음" if right else "틀림", r.ai_calls, f"{took:.0f}", ins, outs,
                             ",".join(hits) or "-", (said or fail or "-")[:80].replace("|", "/")))
                print(f"  {model[7:]:12s} {name:24s} {rows[-1][2]}  호출 {r.ai_calls}  {took:.0f}초  토큰 {ins}+{outs}  눌린 것 {rows[-1][7]}")
    finally:
        srv.shutdown()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(f"# AI 도움 손 시험 ({time.strftime('%Y-%m-%d %H:%M')})\n\n")
        f.write("| 모델 | 화면 | 결과 | 호출 | 초 | 입력 토큰 | 출력 토큰 | 눌린 것 | AI 가 본 화면 |\n|---|---|---|---|---|---|---|---|---|\n")
        for row in rows:
            f.write("| " + " | ".join(str(x) for x in row) + " |\n")
        for model in MODELS:
            mine = [x for x in rows if x[0] == model]
            f.write(f"\n- {model}: 맞음 {sum(x[2] == '맞음' for x in mine)}/{len(mine)}, 입력 {sum(x[5] for x in mine)} · "
                    f"출력 {sum(x[6] for x in mine)} 토큰\n")
    print(f"\n결과: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
