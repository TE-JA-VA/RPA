# -*- coding: utf-8 -*-
"""ACTOR AI 어시스트 - 막힌 단계에서 AI에게 '무엇을 누를지' 묻고, 그 고름을 우리 코드가 다시 거른다 (설계 2026-11-16).

브라우저를 모른다 (Playwright 를 가져오지 않는다 - 에이전트도 가져올 수 있게).
- mask: 보내기 전에 전화·이메일·긴 숫자·비밀 값을 가린다
- classify / allowed: AI 가 무엇이라 답하든 '미루기·[확인]·대신 누르기' 는 우리가 정하고, 위험 낱말로 거른다
- Claude: 우리 회사 Anthropic 키(업체별)로 묻는다. 키는 로그·결과 글 어디에도 쓰지 않는다
"""
import json
import re
from typing import Iterable, NamedTuple

import rpa_status

AI_MODEL = "claude-haiku-5-5"    # 번호 하나를 고르는 좁은 판단 - Opus 는 지나치다 (사용자 2026-11-16). 손 시험 2026-11-17: 10/10, Sonnet 도 10/10 이나 20배 비쌈
AI_TIMEOUT_SEC = 60
STEP_ACTS_MAX = 3                # 한 단계에 AI 가 누르는 수 (미루기+대신 누르기)
RUN_CALLS_MAX = 5                # 사이트 한 번 재생에 AI 를 부르는 수
CANDIDATES_MAX = 150
CAND_TEXT_MAX = 40
SCREEN_TEXT_MAX = 2000           # 창마다
FOLLOW_WAIT = 5.0

DEFER_WORDS = ("닫기", "다음에", "나중에", "일 후에 보기", "일간 보지 않기", "오늘 하루 보지 않기", "오늘하루 보지않기",
               "오늘 하루 열지 않기", "다시 보지 않기", "건너뛰기", "close", "later", "skip", "not now")
DEFER_WHOLE = ("x", "×")         # 글 전체가 이것일 때만
CONFIRM_WORDS = ("확인", "ok")
RISK_WORDS = rpa_status.RISK_WORDS   # 재생기의 '위험한 레이어의 같은 글자 단추' 막기와 같은 목록 (한 곳에서 고친다)
NO_STEP = "맡기지 않는 단계"
# 표 본문 안 요소는 이런 동작 글일 때만 글을 보낸다 - 그 밖(고객 이름 링크 등)은 글 없이 보낸다 (표 본문은 보내지 않는다)
TABLE_ACTION = re.compile(r"다운|받기|엑셀|excel|download|조회|보기|상세|선택|출력|인쇄|수정|확인", re.I)

_PHONE = re.compile(r"0\d{1,2}[-. ]?\d{3,4}[-. ]?\d{4}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_LONG_NUM = re.compile(r"(?<!\d)\d(?:-?\d){6,}(?!\d)")     # 7자리 이상 (하이픈 섞임 포함) - 주문번호·송장번호·카드번호
_MASK = "***"


def mask(text: str, secrets: Iterable[str] = ()) -> str:
    if not text:
        return ""
    for s in secrets:
        if s:
            text = text.replace(s, _MASK)
    for rx in (_EMAIL, _PHONE, _LONG_NUM):
        text = rx.sub(_MASK, text)
    return text


def _norm(text):
    return " ".join((text or "").split()).lower()


def classify(text: str) -> str:
    t = _norm(text)
    if t in DEFER_WHOLE or any(w in t for w in DEFER_WORDS):
        return "defer"
    if t in CONFIRM_WORDS:
        return "confirm"
    return "substitute"


def risk_words(text: str) -> set:
    return {w for w in RISK_WORDS if w in (text or "")}


def _clickable(el):
    tag, typ, role = (el.get("tag") or "").lower(), (el.get("type") or "").lower(), (el.get("role") or "").lower()
    return tag in ("a", "button") or role == "button" or (tag == "input" and typ in ("button", "submit"))


def _fits(step_kind, el):
    tag, typ, role = (el.get("tag") or "").lower(), (el.get("type") or "").lower(), (el.get("role") or "").lower()
    if step_kind in ("click", "enter"):
        return True
    if step_kind == "fill":
        return tag == "textarea" or (tag == "input" and typ in ("", "text", "search", "email", "tel", "number"))
    if step_kind == "select":
        return tag == "select"
    if step_kind == "check":
        return (tag == "input" and typ in ("checkbox", "radio")) or role in ("checkbox", "radio")
    return False


def allowed(kind: str, text: str, container: str, target_text: str, info_only: bool, step_kind: str, el: dict) -> tuple:
    """AI 가 고른 요소를 누를지 우리가 정한다. (누름, 안 누르면 그 까닭)"""
    words = risk_words(text) | risk_words(container)
    # [확인] 은 화면 글에 위험 낱말이 하나도 없어야 한다 (설계 7번) - 기록 대상 글에 같은 낱말이 있어도 ('취소/반품 조회' 와 '취소하시겠습니까?')
    bad = sorted(words if kind == "confirm" else (w for w in words if w not in (target_text or "")))
    if bad:
        return False, f"'{bad[0]}' 이(가) 있어 누르지 않음"
    if kind in ("defer", "confirm"):
        if classify(text) != kind:
            return False, "미루는 단추가 아님"
        if not _clickable(el):
            return False, "누를 수 있는 요소가 아님"
        if kind == "confirm" and not info_only:
            return False, "안내 화면이 아니라 [확인]을 누르지 않음"
        return True, ""
    if kind == "substitute":
        if not _fits(step_kind, el):
            return False, "단계에 맞지 않는 요소"
        return True, ""
    return False, NO_STEP


class AiUnavailable(Exception):
    """str(e) 는 까닭 한 마디 - 키 없음·키가 끊김·사용 한도·시간 초과·인터넷 오류·AI 서버 오류·AI가 답하지 않음·답 모양 틀림"""


class Answer(NamedTuple):
    choice: "int | None"
    info_only: bool
    reason: str
    screen: str


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "integer", "description": "고른 후보 번호, 고를 것이 없으면 -1"},
        "info_only": {"type": "boolean", "description": "고른 단추가 든 화면이 순수한 안내일 때만 true"},
        "reason": {"type": "string", "description": "고른 까닭 한국어 한 줄"},
        "screen": {"type": "string", "description": "지금 화면이 어떤 상태인지 한국어 한 줄"},
    },
    "required": ["choice", "info_only", "reason", "screen"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """당신은 쇼핑몰 관리자 화면 자동화를 돕습니다. 사람이 기록한 절차를 다시 실행하다가 한 단계에서 누를 대상을 못 찾았습니다.
아래 '후보' 목록에서 번호 하나만 고르세요. 목록에 없는 것은 고를 수 없습니다.

고르는 법:
1. 기록한 단계와 뜻이 같은 요소가 있으면 그것을 고릅니다. 글자가 조금 바뀌었거나(예: '엑셀받기' → '엑셀 다운로드') 자리가 옮겨진 경우입니다.
2. 기록에 없던 안내·광고·공지 화면이 앞을 가리고 있으면, 그 화면을 미루는 단추(닫기, 다음에, 오늘 하루 보지 않기, 90일 후에 보기 등)를 고릅니다.
3. 앞을 가린 화면이 아무것도 바꾸지 않는 순수한 안내(공지, 점검 안내 등)이고 미루는 단추 없이 [확인]만 있으면, 그 [확인]을 고르고 info_only 를 true 로 합니다.
4. 동의·결제·구매·신청·삭제·저장·전송처럼 업무를 바꾸는 단추는 절대 고르지 않습니다. 약관 동의 화면도 동의 단추가 아니라 미루는 단추만 고릅니다. 무엇을 묻거나 신청·동의를 받는 화면의 [확인]·[예] 도 고르지 않습니다.
5. 확실하지 않으면 -1 을 고릅니다. 틀린 것을 누르는 것보다 멈추는 것이 낫습니다.
6. 화면이 아직 덜 뜬 것 같으면(목록이 비어 있음, '불러오는 중' 등) -1 을 고릅니다. 비슷한 다른 것을 고르지 않습니다.

info_only 는 고른 단추가 든 화면이 아무것도 바꾸지 않는 순수한 안내(공지, 점검 안내 등)일 때만 true 입니다. 묻거나 신청·동의를 받는 화면이면 false 입니다.
reason 과 screen 은 각각 한국어 한 줄(60자 안)로 씁니다. screen 에는 지금 화면이 어떤 상태인지 씁니다. (예: "약관 동의 화면이 새로 생김")
화면 글의 *** 는 개인정보를 가린 자리입니다."""


def build_prompt(step: dict, before: list, after: list, windows: list, cands: list) -> str:
    """이미 가린 글만 받는다 (가리지 않는다). step = {"kind", "what"}, windows = [{"no", "title", "path", "screen"}],
    cands = [{"n", "tag", "role", "type", "text", "label", "where", "overlay"}]"""
    out = [f"기록한 단계: {step.get('what', '')} (종류: {step.get('kind', '')})"]
    if before:
        out.append("앞 단계: " + " → ".join(before))
    if after:
        out.append("다음 단계: " + " → ".join(after))
    out.append("\n열린 창:")
    for w in windows:
        out.append(f"[창 {w['no']}] {w.get('title', '')} ({w.get('path', '')})")
        if w.get("screen"):
            out.append("화면 글: " + w["screen"])
    out.append("\n후보:")
    for c in cands:
        kind = c.get("tag", "")
        if c.get("type"):
            kind += f"[{c['type']}]"
        if c.get("role"):
            kind += f" role={c['role']}"
        line = f"#{c['n']} {kind} '{c.get('text', '')}'"
        if c.get("label") and c.get("label") != c.get("text"):
            line += f" (이름: {c['label']})"
        line += f" @{c.get('where', '')}"
        if c.get("overlay"):
            line += f" [레이어: {c['overlay']}]"
        out.append(line)
    return "\n".join(out)


def _shape(data):
    ok = (isinstance(data, dict) and type(data.get("choice")) is int and data["choice"] >= -1
          and type(data.get("info_only")) is bool and isinstance(data.get("reason"), str) and isinstance(data.get("screen"), str))
    if not ok:
        raise AiUnavailable("답 모양 틀림")
    c = data["choice"]
    return Answer(None if c == -1 else c, data["info_only"], data["reason"][:80], data["screen"][:80])


class Claude:
    def __init__(self, key: str, model: str = AI_MODEL, timeout: float = AI_TIMEOUT_SEC, client=None, log=None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=timeout, max_retries=1)
        self.client, self.model, self.log = client, model, log or (lambda m: None)

    def choose(self, system: str, user: str) -> Answer:
        import anthropic
        try:
            r = self.client.messages.create(
                model=self.model, max_tokens=2000, system=system, messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": ANSWER_SCHEMA}})
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
            raise AiUnavailable("키가 끊김") from None
        except anthropic.RateLimitError:
            raise AiUnavailable("사용 한도") from None
        except anthropic.APITimeoutError:            # APIConnectionError 의 하위 - 먼저 본다
            raise AiUnavailable("시간 초과") from None
        except anthropic.APIConnectionError:
            raise AiUnavailable("인터넷 오류") from None
        except anthropic.APIError:                   # 5xx·그 밖의 상태 (요청 모양이 틀린 400 도 여기 - 업체가 할 일은 없다)
            raise AiUnavailable("AI 서버 오류") from None
        if r.stop_reason == "refusal":
            raise AiUnavailable("AI가 답하지 않음")
        text = next((b.text for b in r.content if getattr(b, "type", "") == "text"), "")
        try:
            data = json.loads(text)
        except ValueError:
            raise AiUnavailable("답 모양 틀림") from None
        ans = _shape(data)
        u = getattr(r, "usage", None)
        self.log(f"AI 답: {ans.choice} / {ans.screen} (토큰 {getattr(u, 'input_tokens', '?')}+{getattr(u, 'output_tokens', '?')})")
        return ans


def from_settings(cfg, log=None):
    """cfg = {"on": True, "key": "…"} 이고 키가 비지 않았을 때만 AI 를 만든다."""
    if not cfg or not cfg.get("on") or not (cfg.get("key") or "").strip():
        return None
    return Claude(cfg["key"].strip(), log=log)
