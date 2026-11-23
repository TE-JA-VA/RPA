# -*- coding: utf-8 -*-
"""release/installer.iss 를 버전 종류마다 펼쳐 보는 작은 ISPP 흉내 (시험용 - tests/test_installer_edition.py·test_build_release.py).

#if Name == "x" / #ifdef / #ifndef / #else / #endif 만 가른다. expand=True 면 살아 남은 가지의 #define Name "값" 을 모아
{#Name} 을 그 값으로 바꾼다 (ISCC 가 만드는 글과 같게 - 일반 버전의 자리 글자가 예전 그대로인지 보는 데 쓴다).
"""
import re


def preprocess(text, defines, expand=False):
    """남는 줄 (지시문 줄은 뺀다). defines 는 /D 로 넘기는 값 {"Edition": "cloud", ...}."""
    out, stack, values = [], [], dict(defines)
    for line in text.splitlines():
        s = line.strip()
        m = re.fullmatch(r'#if\s+(\w+)\s*==\s*"([^"]*)"', s)
        if m:
            stack.append(values.get(m.group(1)) == m.group(2))
        elif s.startswith("#ifdef "):
            stack.append(s.split()[1] in values)
        elif s.startswith("#ifndef "):
            stack.append(s.split()[1] not in values)
        elif s == "#else":
            stack[-1] = not stack[-1]
        elif s == "#endif":
            stack.pop()
        elif s.startswith("#"):
            d = re.fullmatch(r'#define\s+(\w+)\s+"([^"]*)"', s)
            if d and all(stack):
                values[d.group(1)] = d.group(2)
            continue
        elif all(stack):
            out.append(line)
    assert not stack, "#if 와 #endif 의 짝이 맞지 않는다"
    text = "\n".join(out)
    if expand:
        text = re.sub(r"\{#(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), text)
    return text
