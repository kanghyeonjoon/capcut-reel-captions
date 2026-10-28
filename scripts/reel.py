#!/usr/bin/env python3
"""컷 편집이 끝난 캡컷(맥 9.5) 프로젝트에 릴스 자막·첫 화면 제목·마지막 글을 넣는다. 컷 편집은 건드리지 않는다.

  find                       최근 캡컷 프로젝트(열림 여부, 길이, 비율, 컷 수, 글자 수, 원본 파일)
  prep  <프로젝트>           원본 파일마다 받아쓰기(받아쓰기/*.json)와 소리 크기(소리크기/*.bin)를 만든다
  plan  <프로젝트>           받아쓰기를 컷에 맞춰 짧은 자막으로 나눠 plan.json 초안을 쓴다(사람이 다듬는다)
  apply <프로젝트> [--dry]   plan.json을 캡컷 파일에 쓴다. 캡컷에서 프로젝트를 닫은 뒤에만 쓴다.

<프로젝트>는 캡컷 프로젝트 이름(com.lveditor.draft 아래 폴더) 또는 그 폴더 경로다.
작업 폴더(--work)는 기본 ~/영상편집/<이름>_자막 이다. 받아쓰기·plan.json·백업·넣은 기록이 여기 모인다.
"""
import argparse
import copy
import difflib
import glob
import json
import os
import re
import shutil
import statistics
import struct
import subprocess
import sys
import time
import unicodedata
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
BIN = os.path.join(HERE, "bin")
DRAFTS = os.path.expanduser("~/Movies/CapCut/User Data/Projects/com.lveditor.draft")
FRAME = 0.02  # 소리 크기 한 칸(20ms)
CAPTION_LEAD = 0.05  # 자막은 실제 말소리보다 이만큼 먼저 뜬다
SENT_END = re.compile(r"[.?!]$")
# 이 말로 끝나면 다음 말과 붙어 있어야 자연스럽다(꾸미는 말). 줄 끝에 두지 않는다.
CLINGY = {"그런", "어떤", "이런", "저런", "무슨", "왜", "이", "그", "저", "더", "좀", "좀만", "제", "내", "몇", "한", "두", "세", "안", "못",
          "잘", "너무", "정말", "진짜", "되게", "다", "또", "그냥", "막", "딱", "꼭", "같은", "어느", "모든", "새", "첫",
          "전혀", "결코", "절대", "아무리", "단", "나", "가장", "너무나", "그저", "오직", "최소한", "훨씬"}
# 이 말로 끝나면 줄을 끊기 좋다(이어 주는 끝).
LINKING = ("는데", "은데", "지만", "니까", "면서", "려고", "도록", "라고", "다고", "는지", "고", "서", "면", "며", "자", "뿐")
# 앞말에 기대는 보조 용언. 줄 첫머리에 두지 않는다('알고 / 나서', '설명해야 / 될지').
# 의존 명사('5년 / 동안')도 앞말과 한 덩어리라 줄 첫머리에 두지 않는다.
AUX = ("나서", "싶", "있었", "있어", "있는", "보니", "버리", "버렸", "될지", "되었", "됐", "하는지", "주는", "줬",
       "동안", "때", "것", "수", "적", "뿐", "만큼", "대해", "대한", "위해", "위한", "통해", "같이", "처럼")
# 컷 경계에 걸친 이 말들은 대개 사람이 잘라 낸 군말이다. 걸쳐 있으면 자막에서 뺀다(짧은 자막에도 맞다).
FILLERS = {"저는", "제가", "그래서", "그리고", "근데", "그런데", "그러니까", "그", "음", "어", "아", "뭐", "이제", "약간", "막"}


def nid():
    return str(uuid.uuid4()).upper()


def u16(text):
    return len(text.encode("utf-16-le")) // 2


def us(sec):
    return round(sec * 1e6)


def say(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 프로젝트 읽기

def folder_of(name):
    f = name if os.path.isdir(name) else os.path.join(DRAFTS, name)
    if not os.path.isfile(os.path.join(f, "draft_info.json")):
        sys.exit("캡컷 프로젝트를 찾지 못했습니다: %s  (find로 이름을 확인하세요)" % name)
    return os.path.abspath(f)


def work_of(folder, work):
    w = work or os.path.expanduser("~/영상편집/%s_자막" % os.path.basename(folder.rstrip("/")))
    os.makedirs(w, exist_ok=True)
    return w


def load(folder):
    return json.load(open(os.path.join(folder, "draft_info.json"), encoding="utf-8"))


def index(info):
    by = {}
    for kind, lst in info["materials"].items():
        if isinstance(lst, list):
            for m in lst:
                if isinstance(m, dict) and "id" in m:
                    by[m["id"]] = (kind, m)
    return by


def is_open(folder):
    return os.path.exists(os.path.join(folder, ".locked"))


def cuts_of(info, by):
    """주 영상 트랙(영상 길이 합이 가장 긴 video 트랙)의 조각들 = 컷. 타임라인 순서, 1부터 번호."""
    best, best_len = [], 0
    for t in info["tracks"]:
        if t["type"] != "video":
            continue
        segs = [s for s in t["segments"] if by.get(s["material_id"], ("", {}))[0] == "videos"]
        total = sum(s["target_timerange"]["duration"] for s in segs)
        if total > best_len:
            best, best_len = segs, total
    out = []
    for n, s in enumerate(sorted(best, key=lambda s: s["target_timerange"]["start"]), start=1):
        m = by[s["material_id"]][1]
        src = s.get("source_timerange") or {"start": 0, "duration": s["target_timerange"]["duration"]}
        tt = s["target_timerange"]
        out.append({"n": n, "seg": s, "path": m.get("path", ""), "photo": m.get("type") == "photo",
                    "t0": tt["start"] / 1e6, "t1": (tt["start"] + tt["duration"]) / 1e6,
                    "s0": src["start"] / 1e6, "s1": (src["start"] + src["duration"]) / 1e6, "speed": s.get("speed") or 1.0})
    return out


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


# ---------------------------------------------------------------- find

def cmd_find(a):
    rows = []
    for name in os.listdir(DRAFTS):
        f = os.path.join(DRAFTS, name)
        p = os.path.join(f, "draft_info.json")
        if not os.path.isfile(p):
            continue
        try:
            info = load(f)
        except (ValueError, UnicodeDecodeError):
            continue  # 암호화됐거나 읽을 수 없는 프로젝트
        by = index(info)
        cs = cuts_of(info, by)
        texts = sum(len(t["segments"]) for t in info["tracks"] if t["type"] == "text")
        srcs = sorted({os.path.basename(c["path"]) for c in cs if not c["photo"]})
        rows.append((os.path.getmtime(p), name, is_open(f), info.get("duration", 0) / 1e6,
                     (info.get("canvas_config") or {}).get("ratio", "?"), len(cs), texts, srcs))
    rows.sort(reverse=True)
    for mt, name, op, dur, ratio, n, texts, srcs in rows[:a.limit]:
        say("%-24s %-6s %s  %5.1f초 %-5s 컷 %3d개  글자 %3d개  원본: %s" % (
            name, "[열림]" if op else "", time.strftime("%m/%d %H:%M", time.localtime(mt)), dur, ratio, n, texts,
            ", ".join(srcs[:3]) + (" 외 %d개" % (len(srcs) - 3) if len(srcs) > 3 else "")))


# ---------------------------------------------------------------- prep

def tool(name):
    exe, src = os.path.join(BIN, name), os.path.join(HERE, name + ".swift")
    if not os.path.exists(exe) or os.path.getmtime(src) > os.path.getmtime(exe):
        os.makedirs(BIN, exist_ok=True)
        say("도구 만드는 중:", name)
        subprocess.run(["swiftc", "-O", src, "-o", exe], check=True)
    return exe


def cut_list(cs):
    """편집본 소리를 만들 때 쓰는 컷 목록(파일@원본시작@원본길이@타임라인시작@속도)."""
    return ["%s@%.6f@%.6f@%.6f@%g" % ("-" if c["photo"] else c["path"], c["s0"], c["s1"] - c["s0"], c["t0"], c["speed"]) for c in cs]


def cmd_prep(a):
    """컷 편집된 그대로의 소리를 만들어 받아쓴다. 원본을 받아쓰고 컷에 맞춰 옮기면 컷 경계에서 반쯤 잘린 낱말을
    가려낼 수 없지만, 편집본 소리를 받아쓰면 실제로 들리는 말만 나오고 시각도 타임라인 시각 그대로다."""
    folder = folder_of(a.project)
    work = work_of(folder, a.work)
    info = load(folder)
    cs = cuts_of(info, index(info))
    missing = sorted({c["path"] for c in cs if not c["photo"] and not os.path.exists(c["path"])})
    if missing:
        sys.exit("원본 파일이 없습니다(옮겨졌나요?):\n  " + "\n  ".join(missing))
    items = cut_list(cs)
    os.makedirs(os.path.join(work, "받아쓰기"), exist_ok=True)
    os.makedirs(os.path.join(work, "소리크기"), exist_ok=True)
    sig = os.path.join(work, "받아쓰기", "편집본_컷.json")
    audio = os.path.join(work, "받아쓰기", "편집본.m4a")
    tj, eb = os.path.join(work, "받아쓰기", "편집본.json"), os.path.join(work, "소리크기", "편집본.bin")
    same = os.path.exists(sig) and json.load(open(sig, encoding="utf-8")) == items
    if same and os.path.exists(tj) and os.path.exists(eb) and not a.force:
        say("컷 편집이 그대로라 전에 만든 받아쓰기를 씁니다:", tj)
        return
    subprocess.run([tool("timeline_audio"), audio] + items, check=True)
    subprocess.run([tool("envelope"), audio, eb], check=True)
    say("받아쓰는 중(1분 영상에 1분쯤)...")
    subprocess.run([tool("transcribe"), audio, tj], check=True)
    json.dump(items, open(sig, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    say("작업 폴더:", work)


# ---------------------------------------------------------------- plan

def read_env(path):
    if not os.path.exists(path):
        return None
    b = open(path, "rb").read()
    return struct.unpack("%df" % (len(b) // 4), b)


def env_at(env, a, b):
    return env[max(0, int(a / FRAME)):max(0, int(b / FRAME)) + 1] if env else ()


def syllables(word):
    return max(1, len(re.findall(r"[가-힣0-9A-Za-z]", word)))


def end_guess(w):
    """받아쓰기의 낱말 끝은 다음 낱말 시작까지 늘어나 있다. 글자 수로 실제 끝을 어림한다."""
    return min(w["e"], w["s"] + 0.15 * syllables(w["t"]) + 0.05)


def clean(word):
    return word.strip().rstrip(".,")


def phrases(words, env, thr, pause):
    """끊어 읽는 자리(문장 끝, 쉼표, 소리가 pause초 넘게 끊긴 곳)에서 나눈 말 덩어리들.
    컷이 바뀌는 곳은 말이 이어지는 경우가 많아(더듬은 곳만 잘라 냄) 여기서는 나누지 않고, 줄 나눌 때 끊기 좋은 자리로만 친다."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = nxt is None or SENT_END.search(w["t"].strip()) or w["t"].strip().endswith(",")
        if not brk and env:
            # 받아쓰기 시각이 조금씩 어긋나므로, 이 낱말 중간부터 다음 낱말 시작 조금 뒤까지에서 가장 긴 조용한 구간을 잰다
            run = longest = 0
            for v in env_at(env, (w["s"] + end_guess(w)) / 2, nxt["s"] + 0.1):
                run = run + 1 if v < thr else 0
                longest = max(longest, run)
            # 꾸미는 말 뒤에서 머뭇거린 것('왜 그런... 상황에서')은 끊지 않는다
            brk = longest * FRAME >= pause and clean(w["t"]) not in CLINGY
            # 짧은 낱말 하나만 남는 줄("세금 / 내는 법")은 깜빡 지나가니, 머뭇거렸어도 다음 말과 붙인다
            if brk and len(cur) == 1 and len(clean(w["t"])) <= 3:
                brk = False
        if brk:
            out.append(cur)
            cur = []
    return out


def split_phrase(ph, cap):
    """한 덩어리를 줄로 나눈다. 레퍼런스처럼 줄은 짧게(target자 안팎, 1.5초 안쪽),
    꾸미는 말로 끝나거나 보조 용언('나서', '싶어', '될지')으로 시작하지 않게, 이어 주는 끝·컷이 바뀌는 곳에서 끊기게."""
    n = len(ph)
    texts = [clean(w["t"]) for w in ph]
    best = [0.0] + [float("inf")] * n
    back = [0] * (n + 1)
    for i in range(1, n + 1):
        for j in range(max(0, i - cap["max_words"]), i):
            line = " ".join(texts[j:i])
            if len(line) > cap["max_chars"] and i - j > 1:
                continue
            last = texts[i - 1]
            dur = (ph[i]["s"] if i < n else end_guess(ph[i - 1])) - ph[j]["s"]
            cost = 0.15 * (len(line) - cap.get("target_chars", 7)) ** 2 + 1.5 + 2.0 * max(0.0, dur - cap.get("max_seconds", 1.5))
            if i < n:
                if last in CLINGY:
                    cost += 6.0
                if last.endswith(("을", "를")):
                    cost += 1.0  # 목적어와 서술어는 붙여 둔다
                if texts[i].startswith(AUX):
                    cost += 2.5
                elif last.endswith(LINKING):
                    cost -= 1.0
                if ph[i]["cut"] != ph[i - 1]["cut"]:
                    cost -= 1.0  # 컷이 바뀌는 자리
            if best[j] + cost < best[i]:
                best[i], back[i] = best[j] + cost, j
    lines, i = [], n
    while i > 0:
        lines.append(ph[back[i]:i])
        i = back[i]
    return lines[::-1]


def norm(t):
    return re.sub(r"[^가-힣0-9A-Za-z]", "", t)


def align_script(words, script):
    """대본 글이 있으면 받아쓰기 낱말 대신 대본 낱말을 쓴다. 잘못 들은 말·띄어쓰기를 바로잡고, 대본의 마침표·쉼표로
    줄을 나눌 수 있게 된다. 시각은 받아쓰기에서 가져온다(차례대로 맞추고, 받아쓰기가 놓친 낱말은 앞뒤 사이에 끼운다)."""
    C = [w for w in script.split() if norm(w)]
    sm = difflib.SequenceMatcher(None, [norm(w["t"]) for w in words], [norm(w) for w in C], autojunk=False)
    times = [None] * len(C)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op in ("equal", "replace"):
            for k in range(j1, j2):
                pos = (k - j1) * (i2 - i1) / (j2 - j1)
                w = words[i1 + int(pos)]
                times[k] = (w["s"] + (pos - int(pos)) * (end_guess(w) - w["s"]), w["cut"])
    out = []
    for k, w in enumerate(C):
        if times[k] is None:  # 받아쓰기가 놓친 낱말: 앞 낱말과 뒤 낱말 사이
            prev = next((times[j] for j in range(k - 1, -1, -1) if times[j]), (0.0, words[0]["cut"]))
            nxt = next((times[j] for j in range(k + 1, len(C)) if times[j]), (prev[0] + 0.4, prev[1]))
            times[k] = ((prev[0] + nxt[0]) / 2, prev[1])
        out.append({"t": " " + w, "s": round(times[k][0], 3), "cut": times[k][1]})
    for i, w in enumerate(out):
        w["e"] = out[i + 1]["s"] if i + 1 < len(out) else w["s"] + 0.15 * syllables(w["t"]) + 0.1
    return out


def cmd_plan(a):
    folder = folder_of(a.project)
    work = work_of(folder, a.work)
    style = load_style(a.style)
    cap = style["caption"]
    info = load(folder)
    total = info["duration"] / 1e6
    cs = cuts_of(info, index(info))
    calm = {int(x) for x in a.calm_cuts.split(",") if x.strip()} if a.calm_cuts else set()
    tj = os.path.join(work, "받아쓰기", "편집본.json")
    sig = os.path.join(work, "받아쓰기", "편집본_컷.json")
    if not os.path.exists(tj):
        sys.exit("받아쓰기가 없습니다: %s  (먼저 prep)" % tj)
    if json.load(open(sig, encoding="utf-8")) != cut_list(cs):
        sys.exit("받아쓴 뒤로 컷 편집이 바뀌었습니다. prep을 다시 하세요.")
    env = read_env(os.path.join(work, "소리크기", "편집본.bin"))
    thr = None
    if env:
        q = sorted(env)
        floor, speech = q[len(q) // 5], q[len(q) * 4 // 5]
        thr = floor + (speech - floor) / 3  # 바닥 소음 가까이: 작게 낸 소리를 쉼으로 잘못 보지 않게
        # 말소리 시작 찾기용 기준. 쉼을 잘라 낸 편집본은 조용한 칸이 적어 20%선이 말소리에 걸리므로 5%선을 바닥으로 본다
        on_thr = q[len(q) // 20] + 4.0

    def voice_onset(w):
        """받아쓰기 낱말 구간은 [앞 낱말 끝, 이 낱말 끝]이라 앞쪽 쉼이 붙어 있다(그대로 쓰면 자막이 말보다 먼저 뜬다).
        구간 시작부터 소리가 0.06초 넘게 이어지는 첫 곳을 찾는다. 맨 앞의 짧은 소리(0.12초 안에 끊김)는 앞 낱말 꼬리라 건너뛴다."""
        if not env:
            return w["s"]

        def lv(t):
            i = int(t / FRAME)
            return env[i] if 0 <= i < len(env) else -99.0
        t, end = w["s"], w["e"] - 0.02
        if lv(t) >= on_thr:
            while t < min(w["s"] + 0.12, end) and lv(t) >= on_thr:
                t += FRAME
            if t >= w["s"] + 0.12 or t >= end:
                return w["s"]
        run = 0
        while t < end:
            run = run + 1 if lv(t) >= on_thr else 0
            if run >= 3:
                return t - 2 * FRAME
            t += FRAME
        return w["s"]

    def cut_at(t):
        return next((c["n"] for c in cs if c["t0"] <= t < c["t1"]), cs[-1]["n"] if cs else 0)

    # 편집본 소리를 받아썼으니 시각이 곧 타임라인 시각이다. 컷 경계에 걸친 낱말만 표시해 둔다.
    words, checks = [], []
    for w in (w for s in json.load(open(tj, encoding="utf-8"))["segments"] for w in s["words"]):
        if not clean(w["t"]):
            continue
        w = dict(w, s=round(max(w["s"], voice_onset(w) - CAPTION_LEAD), 2))
        w["cut"] = cut_at(w["s"] + 0.05)
        c = cs[w["cut"] - 1]
        stamp = "%d:%04.1f 컷%d" % (int(w["s"] // 60), w["s"] % 60, w["cut"])
        if end_guess(w) > c["t1"] + 0.05 or w["s"] < c["t0"] - 0.05 or (w["s"] - c["t0"] < 0.15 and (c["n"] > 1 or c["s0"] > 0.2)):
            if clean(w["t"]) in FILLERS:
                checks.append("%s 경계에 걸친 군말이라 뺌: '%s'" % (stamp, clean(w["t"])))
                continue
            checks.append("%s 경계에 걸침, 반쯤 잘린 말일 수 있음: '%s'" % (stamp, clean(w["t"])))
        words.append(w)

    # 말소리 크기(말하는 칸만)로 소리 키울 양을 정한다
    levels = [v for w in words for v in env_at(env, w["s"], end_guess(w))] if env else []
    volume = None
    if levels:
        ld = style["loudness"]
        med, top = statistics.median(levels), max(levels)
        gain = max(0.0, min(ld["target_db"] - med, ld["ceiling_db"] - top, ld["max_gain_db"]))
        if gain >= 1.0:
            volume = round(10 ** (gain / 20), 2)
        say("말소리 가운데 %.1fdB, 가장 큰 곳 %.1fdB → %s" % (med, top, "%.1fdB 키움(volume %.2f)" % (gain, volume) if volume else "그대로"))

    if a.script:
        words = align_script(words, open(a.script, encoding="utf-8").read())
        say("자막 글은 대본 글로 씀: %s" % a.script)

    lines = []
    for ph in phrases(words, env, thr, a.pause):
        lines += split_phrase(ph, cap)

    out = []
    for ln in lines:
        c = cs[ln[0]["cut"] - 1]
        st = max(ln[0]["s"], 0.0)
        if st - c["t0"] < 0.15 and (not out or out[-1]["cut"] != c["n"]):
            st = c["t0"]  # 컷 첫 말이면 컷과 같이 뜨게
        out.append({"text": " ".join(clean(w["t"]) for w in ln), "start": round(st, 2), "end": None, "cut": c["n"],
                    "kind": "calm" if c["n"] in calm else "main",
                    "words": " ".join("%s@%.2f" % (clean(w["t"]), w["s"]) for w in ln), "_last": end_guess(ln[-1])})
    for i, l in enumerate(out):
        nxt = out[i + 1]["start"] if i + 1 < len(out) else None
        if nxt is not None:
            l["end"] = nxt if nxt - l["_last"] < 0.8 else round(l["_last"] + 0.3, 2)
        else:
            l["end"] = round(total if total - l["_last"] < 2.0 else l["_last"] + 0.5, 2)
        del l["_last"]

    t = style["title"]
    titles = [{"text": "", "start": 0.0, "end": round(min(t["seconds"], total), 2), "size": t["size"], "y": t["y"], "kind": t["kind"],
               "note": "첫 화면 제목: 영상 속 본인 말에서 따온 한두 줄(\\n으로 줄바꿈). 비워 두면 넣지 않는다."}]
    for e in style.get("ending", []):
        titles.append({"text": e["text"], "start": round(total - e["before_end"], 2), "end": round(total, 2), "size": e["size"],
                       "y": e["y"], "kind": e["kind"]})
    plan = {"project": os.path.basename(folder), "folder": folder, "style": a.style, "duration": round(total, 3),
            "volume": volume, "zoom": style.get("zoom_default", True), "sound_effects": True, "calm_cuts": sorted(calm), "lines": out, "titles": titles, "checks": checks}
    path = os.path.join(work, "plan.json")
    if os.path.exists(path) and not a.force:
        path = os.path.join(work, "plan_새초안.json")
        say("plan.json이 이미 있어 %s 에 씁니다(덮어쓰려면 --force)." % os.path.basename(path))
    json.dump(plan, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    show(plan)
    say("\n살펴볼 곳:")
    for c in checks:
        say("  -", c)
    say("\n초안:", path)


def show(plan):
    say(" #  시작-끝         컷  모양  자막")
    for i, l in enumerate(plan["lines"], 1):
        say("%2d  %5.2f-%5.2f  %3s  %-4s  %s" % (i, l["start"], l["end"], l.get("cut", ""), l.get("kind", "main"), l["text"]))
    for t in plan.get("titles", []):
        if t["text"]:
            say("글  %5.2f-%5.2f  y %.2f  %s" % (t["start"], t["end"], t["y"], t["text"].replace("\n", " / ")))
    say("소리: %s   확대: %s   감성 컷: %s" % (plan.get("volume") or "그대로", "켬" if plan.get("zoom") else "끔", plan.get("calm_cuts") or "없음"))


# ---------------------------------------------------------------- apply

def load_style(name):
    p = name if os.path.isfile(name) else os.path.join(SKILL, "assets", "styles", name + ".json")
    return json.load(open(p, encoding="utf-8"))


_font_cache = {}


def find_font(title, prefer):
    """그 글꼴을 쓴 캡컷 프로젝트(이 프로젝트 먼저, 그다음 최근 것부터)에서 글꼴 파일 경로와 번호를 가져온다."""
    if title in _font_cache:
        return _font_cache[title]
    folders = [prefer] + sorted(glob.glob(os.path.join(DRAFTS, "*")), key=lambda f: -os.path.getmtime(f))
    for f in folders:
        try:
            d = load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        for m in d["materials"].get("texts", []):
            if m.get("font_title") == title and m.get("font_path") and os.path.exists(m["font_path"]):
                entry = next((x for x in m.get("fonts") or [] if x.get("resource_id") == m.get("font_resource_id")), None)
                entry = dict(entry or {"resource_id": m.get("font_resource_id", ""), "path": m["font_path"], "source_platform": 1},
                             title=title)
                _font_cache[title] = {"title": title, "path": m["font_path"], "rid": m.get("font_resource_id", ""), "entry": entry}
                return _font_cache[title]
    say("글꼴 '%s'을 찾지 못해 기본 글꼴로 넣습니다. 캡컷에서 아무 글자에 그 글꼴을 한 번 써 두면 다음부터 찾습니다." % title)
    _font_cache[title] = None
    return None


def color_ranges(text, style, marks, base=None, hl_color=None):
    """(시작, 끝, 색, 강조 글인지) 목록. marks가 없으면 숫자를 찾아 강조한다."""
    hl = style["highlight"]
    base = base or style["color"]
    if marks is None:
        marks = [m.group(0).strip() for m in re.finditer(hl["regex"], text) if m.group(0).strip()]
    spans, used = [], 0
    for h in marks:
        i = text.find(h, used)
        if i >= 0:
            spans.append((u16(text[:i]), u16(text[:i + len(h)])))
            used = i + len(h)
    out, pos = [], 0
    for a, b in sorted(spans):
        if a > pos:
            out.append((pos, a, base, False))
        out.append((a, b, hl_color or hl["color"], True))
        pos = b
    if pos < u16(text):
        out.append((pos, u16(text), base, False))
    return out


def solid(color, alpha=1.0):
    return {"render_type": "solid", "solid": {"alpha": alpha, "color": list(color)}}


def dress(mat, text, kind, size, style, folder, marks=None, color=None, point=None):
    """글·글꼴·크기·색(숫자 강조)·테두리·그림자를 정한다. color를 주면 바탕 글자색을 바꾼다(핵심 문장).
    point({"words": [...], "color": [...], "size_add": 2.0})를 주면 그 낱말만 그 색으로 조금 크게 한다(낱말 포인트)."""
    if point:
        marks = point["words"]
    k = style["kinds"][kind]
    f = find_font(k["font"], folder) if k.get("font") else None
    c = json.loads(mat["content"])
    base = {x: v for x, v in c["styles"][0].items() if x not in ("strokes", "shadows", "range", "fill", "font", "size")}
    styles = []
    for a, b, col, is_hl in color_ranges(text, style, marks, color, point and point.get("color")):
        sz = size + point.get("size_add", 0.0) if point and is_hl else size
        s = dict(base, range=[a, b], size=sz, fill={"alpha": 1.0, "content": solid(col)})
        if f:
            s["font"] = {"id": f["rid"], "path": f["path"]}
        if k.get("stroke"):
            s["strokes"] = [{"width": k["stroke"]["width"], "mode": 0, "content": solid(k["stroke"]["color"])}]
        if k.get("shadow"):
            s["shadows"] = [dict({x: v for x, v in k["shadow"].items()}, content=solid([0.0, 0.0, 0.0]))]
        styles.append(s)
    c.update(text=text, styles=styles)
    mat.update(content=json.dumps(c, ensure_ascii=False), font_size=size, border_color="#000000",
               border_width=k["stroke"]["width"] if k.get("stroke") else 0.0, text_color="#ffffff", type="text", add_type=0,
               group_id="", language="", recognize_text="", recognize_task_id="", subtitle_keywords=None, base_content="",
               words={"start_time": [], "end_time": [], "text": []}, current_words={"start_time": [], "end_time": [], "text": []},
               fixed_width=-1.0, line_max_width=0.95)  # 고정 폭이 있으면 세로 화면에서 긴 줄이 두 줄로 꺾인다
    if f:
        mat.update(font_title=f["title"], font_path=f["path"], font_resource_id=f["rid"], fonts=[dict(f["entry"], id=nid())])


def new_text(info, tmpl, text, kind, size, y, st, en, style, folder, marks=None, color=None, point=None):
    s = copy.deepcopy(tmpl["segment"])
    m = copy.deepcopy(tmpl["material"])
    s["id"], m["id"] = nid(), nid()
    info["materials"].setdefault("texts", []).append(m)
    extras = []
    for e in tmpl["extras"]:
        x = dict(copy.deepcopy(e["material"]), id=nid())
        info["materials"].setdefault(e["kind"], []).append(x)
        extras.append(x["id"])
    s["material_id"], s["extra_material_refs"] = m["id"], extras
    dress(m, text, kind, size, style, folder, marks, color, point)
    s["target_timerange"] = {"start": us(st), "duration": us(en) - us(st)}
    s["clip"] = dict(s["clip"], transform={"x": 0.0, "y": y})
    s["common_keyframes"] = []
    return s, [m["id"]] + extras


def scale_keyframes(seg, speed, points):
    base = (seg.get("source_timerange") or {"start": 0})["start"]
    return [{"id": nid(), "material_id": "", "property_type": prop, "keyframe_list": [
        {"id": nid(), "curveType": "Line", "graphID": "", "left_control": {"x": 0.0, "y": 0.0}, "right_control": {"x": 0.0, "y": 0.0},
         "time_offset": base + us(o * speed), "values": [v], "string_value": ""} for o, v in points]}  # 영상 키프레임은 원본 시각
        for prop in ("KFTypeScaleX", "KFTypeScaleY")]


_sfx_cache = {}


def find_sfx(name, prefer):
    """그 효과음을 쓴 캡컷 프로젝트(이 프로젝트 먼저, 그다음 최근 것부터)에서 소리 조각과 재료를 찾는다."""
    if name in _sfx_cache:
        return _sfx_cache[name]
    folders = [prefer] + sorted(glob.glob(os.path.join(DRAFTS, "*")), key=lambda f: -os.path.getmtime(f))
    for f in folders:
        try:
            d = load(f)
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        by = index(d)
        for t in d["tracks"]:
            for s in t["segments"] if t["type"] == "audio" else []:
                kind, m = by.get(s["material_id"], ("", {}))
                if kind == "audios" and unicodedata.normalize("NFC", m.get("name") or "") == unicodedata.normalize("NFC", name) \
                        and os.path.exists(m.get("path", "")):
                    _sfx_cache[name] = {"seg": s, "mats": [(kind, m)] + [by[r] for r in s["extra_material_refs"] if r in by],
                                        "track": {k: v for k, v in t.items() if k != "segments"}}
                    return _sfx_cache[name]
    say("효과음 '%s'을 찾지 못해 건너뜁니다. 캡컷에서 그 효과음을 한 번 써 두면 다음부터 찾습니다." % name)
    _sfx_cache[name] = None
    return None


def new_sfx(info, got, at, max_seconds, volume, total):
    s = copy.deepcopy(got["seg"])
    s["id"] = nid()
    mids = []
    for kind, m in got["mats"]:
        x = dict(copy.deepcopy(m), id=nid())
        info["materials"].setdefault(kind, []).append(x)
        mids.append(x["id"])
    s["material_id"], s["extra_material_refs"] = mids[0], mids[1:]
    dur = got["mats"][0][1].get("duration", 500000) / 1e6
    dur = min(dur, max_seconds or dur, total - at)
    s["target_timerange"] = {"start": us(at), "duration": us(at + dur) - us(at)}
    s["source_timerange"] = {"start": 0, "duration": us(dur)}
    s["volume"], s["common_keyframes"], s["speed"] = volume, [], 1.0
    return s, mids


def clone_seg(info, s):
    """조각과 그 재료들을 새 번호로 복사한다(조각을 둘로 나눌 때)."""
    by = index(info)
    c = copy.deepcopy(s)
    c["id"] = nid()
    ids = []
    for rid in [s["material_id"]] + list(s["extra_material_refs"]):
        if rid not in by:
            continue
        kind, m = by[rid]
        x = dict(copy.deepcopy(m), id=nid())
        info["materials"][kind].append(x)
        ids.append(x["id"])
    c["material_id"], c["extra_material_refs"] = ids[0], ids[1:]
    return c


SNAP = 0.05  # 이보다 가까운 기존 컷 경계가 있으면 새로 자르지 않고 그 경계를 쓴다


def split_at(info, track, t):
    """트랙에서 t초를 지나는 조각을 t에서 둘로 나눈다(소리·화면은 그대로 이어진다).
    t가 기존 경계와 SNAP 안이면 자르지 않는다. 0.01초짜리 조각이 생기면 캡컷이 열 때 한 프레임으로 늘리며
    뒤 조각을 밀어내 말이 사라진다(1028_1 '나 자신을'이 그렇게 잘렸다)."""
    T = us(t)
    for k, s in enumerate(track["segments"]):
        a, d = s["target_timerange"]["start"], s["target_timerange"]["duration"]
        if a < T < a + d:
            if T - a < us(SNAP) or a + d - T < us(SNAP):
                return
            sp = s.get("speed") or 1.0
            src = s["source_timerange"]
            b = clone_seg(info, s)
            s["target_timerange"] = {"start": a, "duration": T - a}
            s["source_timerange"] = {"start": src["start"], "duration": round((T - a) * sp)}
            b["target_timerange"] = {"start": T, "duration": a + d - T}
            b["source_timerange"] = {"start": src["start"] + round((T - a) * sp), "duration": src["duration"] - round((T - a) * sp)}
            b["common_keyframes"] = []
            track["segments"].insert(k + 1, b)
            return


def card_spans(plan, total):
    """plan["cards"]의 시각을 자막 줄 단위로 넓히고(그 줄 전체를 카드로), 겹치면 합친다. 카드 안 줄에는 card 표시."""
    spans = sorted([list(c) for c in plan.get("cards", [])])
    changed = True
    while changed:
        changed = False
        for sp in spans:
            for l in plan["lines"]:
                if l["start"] < sp[1] - 0.02 and l["end"] > sp[0] + 0.02 and (l["start"] < sp[0] or l["end"] > sp[1]):
                    sp[0], sp[1] = min(sp[0], l["start"]), max(sp[1], l["end"])
                    changed = True
    out = []
    for sp in sorted(spans):
        if out and sp[0] <= out[-1][1] + 0.3:
            out[-1][1] = max(out[-1][1], sp[1])
        else:
            out.append([sp[0], min(sp[1], total)])
    for l in plan["lines"]:
        l["card"] = any(l["start"] >= a - 0.02 and l["end"] <= b + 0.02 for a, b in out)
    return out


def check_lines(plan, total):
    """겹침·길이·글자 수를 확인하고 고친다. 문제는 알려 준다."""
    probs = []
    lines = sorted(plan["lines"], key=lambda l: l["start"])
    for i, l in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else total
        if l.get("end") is None or l["end"] > nxt:
            l["end"] = nxt
        l["end"] = min(l["end"], total)
        if l["end"] - l["start"] < 0.25:
            probs.append("너무 짧음(%.2f초): %s" % (l["end"] - l["start"], l["text"]))
        if len(l["text"]) > load_style(plan["style"])["caption"]["max_chars"]:
            probs.append("화면보다 넓을 수 있음(%d자): %s" % (len(l["text"]), l["text"]))
    plan["lines"] = [l for l in lines if l["end"] - l["start"] > 0.05 and l["text"].strip()]
    return probs


def cmd_apply(a):
    folder = folder_of(a.project)
    work = work_of(folder, a.work)
    plan_path = a.plan or os.path.join(work, "plan.json")
    plan = json.load(open(plan_path, encoding="utf-8"))
    style = load_style(plan["style"])
    tmpl = json.load(open(os.path.join(SKILL, "assets", "text_template.json"), encoding="utf-8"))
    info = load(folder)
    total = info["duration"] / 1e6
    probs = check_lines(plan, total)
    show(plan)
    for p in probs:
        say("  주의:", p)
    if a.dry:
        return
    if is_open(folder):
        sys.exit("캡컷에서 이 프로젝트가 열려 있습니다. 캡컷이 닫을 때 덮어쓰므로, 닫은 뒤 다시 실행하세요.")

    # 전에 이 도구로 넣은 것은 지우고 새로 넣는다. 사람이 넣은 글자 트랙은 건드리지 않는다.
    rec_path = os.path.join(work, "넣은기록.json")
    rec = json.load(open(rec_path, encoding="utf-8")) if os.path.exists(rec_path) else {"tracks": [], "materials": [], "cuts": {}}
    info["tracks"] = [t for t in info["tracks"] if t["id"] not in rec["tracks"]]
    gone = set(rec["materials"])
    for kind, lst in info["materials"].items():
        if isinstance(lst, list):
            info["materials"][kind] = [m for m in lst if not (isinstance(m, dict) and m.get("id") in gone)]
    others = [t for t in info["tracks"] if t["type"] == "text" and t["segments"]]
    if others and a.text == "stop":
        sys.exit("이 도구가 넣지 않은 글자 트랙이 %d개(글 %d개) 있습니다. 직접 넣은 것일 수 있습니다.\n"
                 "  그대로 두고 더하려면 --text keep, 지우고 새로 넣으려면 --text replace" % (
                     len(others), sum(len(t["segments"]) for t in others)))
    if a.text == "replace":
        info["tracks"] = [t for t in info["tracks"] if t not in others]

    rec_new = {"tracks": [], "materials": [], "cuts": {}}

    def add_track(segs):
        tr = dict(copy.deepcopy(tmpl["track"]), id=nid(), segments=segs)
        for s in segs:
            s["track_render_index"] = len(info["tracks"])
        info["tracks"].append(tr)
        rec_new["tracks"].append(tr["id"])

    cap_y = style["caption"]["y"]
    segs = []
    emph = style.get("emphasis", {})
    cards = card_spans(plan, total)
    card_style = style.get("card", {"size": 16.0, "y": 0.0})
    for l in plan["lines"]:
        kind = l.get("kind", "main")
        size = l.get("size", style["kinds"][kind]["size"])
        color = None
        if l.get("card"):  # 검은 글자 카드: 화면 가운데 큰 노란 글자
            kind, size, color = "main", card_style["size"], emph.get("color", [1.0, 0.83, 0.2])
            l = dict(l, y=card_style["y"], highlight=[])
        elif l.get("emphasis") and emph:  # 핵심 문장: 다른 색, 조금 크게
            size += emph.get("size_add", 0.0)
            color = emph.get("color")
        s, mids = new_text(info, tmpl, l["text"], kind, size, l.get("y", cap_y),
                           l["start"], l["end"], style, folder, l.get("highlight") if not color else l.get("highlight", []), color,
                           l.get("point"))
        segs.append(s)
        rec_new["materials"] += mids
    add_track(segs)

    lanes = []  # 겹치는 제목·마지막 글은 트랙을 나눠 담는다
    for t in sorted([t for t in plan.get("titles", []) if t["text"].strip()], key=lambda t: t["start"]):
        en = min(t["end"], total)
        s, mids = new_text(info, tmpl, t["text"], t.get("kind", "main"), t["size"], t["y"], t["start"], en, style, folder,
                           t.get("highlight"))
        rec_new["materials"] += mids
        lane = next((ln for ln in lanes if ln[-1]["target_timerange"]["start"] + ln[-1]["target_timerange"]["duration"] <= us(t["start"])), None)
        if lane is None:
            lanes.append([s])
        else:
            lane.append(s)
    for ln in lanes:
        add_track(ln)

    # 효과음: 첫 화면 제목에 휙, 강조 줄("emphasis": true)에 띵, 마지막 글에 딸깍. plan의 "sfx"로 더 넣을 수 있다.
    if plan.get("sound_effects", True) and style.get("sfx"):
        fx = style["sfx"]
        shown = sorted([t for t in plan.get("titles", []) if t["text"].strip()], key=lambda t: t["start"])
        marks = []
        if shown and shown[0]["start"] < 1.0 and "title" in fx:
            marks.append(dict(fx["title"], at=shown[0]["start"]))
        endings = [t for t in shown if t["start"] > 1.0]
        if endings and "ending" in fx:
            marks.append(dict(fx["ending"], at=endings[0]["start"]))
        # 강조 효과음은 이어진 핵심 문장 줄들의 첫 줄에만
        ls = plan["lines"]
        marks += [dict(fx["emphasis"], at=l["start"]) for i, l in enumerate(ls)
                  if l.get("emphasis") and "emphasis" in fx and not (i and ls[i - 1].get("emphasis"))]
        for a, b in card_spans(plan, total) if "emphasis" in fx else []:
            if not any(abs(m["at"] - a) < 0.5 for m in marks):
                marks.append(dict(fx["emphasis"], at=a))
        marks += plan.get("sfx", [])
        sfx_lanes = []
        for mk in sorted(marks, key=lambda m: m["at"]):
            got = find_sfx(mk["name"], folder)
            if not got:
                continue
            s, mids = new_sfx(info, got, mk["at"], mk.get("max_seconds"), mk.get("volume", 0.5), total)
            rec_new["materials"] += mids
            lane = next((ln for ln in sfx_lanes if ln[-1]["target_timerange"]["start"] + ln[-1]["target_timerange"]["duration"]
                         <= s["target_timerange"]["start"]), None)
            if lane is None:
                sfx_lanes.append([s])
                lane_track = got["track"]
            else:
                lane.append(s)
        for ln in sfx_lanes:
            tr = dict(copy.deepcopy(lane_track), id=nid(), segments=ln)
            for s in ln:
                s["track_render_index"] = len(info["tracks"])
            info["tracks"].append(tr)
            rec_new["tracks"].append(tr["id"])
        if marks:
            say("효과음 %d개" % sum(len(ln) for ln in sfx_lanes))

    # 검은 글자 카드: 그 구간 영상만 감춘다(소리는 그대로, 위아래 검은 캔버스와 이어져 화면이 검어진다)
    main_track = max((t for t in info["tracks"] if t["type"] == "video"), key=lambda t: len(t["segments"]), default=None)
    if main_track is not None:
        for s in main_track["segments"]:
            if s["id"] in rec.get("card_segs", []):
                s["clip"] = dict(s.get("clip") or {}, alpha=1.0)
        for a, b in cards:
            split_at(info, main_track, a)
            split_at(info, main_track, b)
        rec_new["card_segs"] = []
        for s in main_track["segments"]:
            st = s["target_timerange"]["start"] / 1e6
            en = st + s["target_timerange"]["duration"] / 1e6
            if any(st >= a - SNAP and en <= b + SNAP for a, b in cards):
                s["clip"] = dict(s.get("clip") or {}, alpha=0.0)
                rec_new["card_segs"].append(s["id"])
        if cards:
            say("검은 글자 카드 %d개: %s" % (len(cards), ", ".join("%.1f~%.1f초" % (a, b) for a, b in cards)))

    # 컷마다 넓게/가깝게 번갈아 + 첫 순간 살짝 크게, 감성 컷은 천천히 다가감. 소리 키우기.
    # 사람이 손댄 컷(이미 확대·키프레임·소리를 바꾼 컷)은 그대로 둔다.
    z = style["zoom"]
    calm = set(plan.get("calm_cuts") or [])
    skipped = []
    for c in cuts_of(info, index(info)):
        s, mine = c["seg"], rec["cuts"].get(c["seg"]["id"], {})
        clip = s.get("clip") or {}
        # 키프레임이 있으면 사람이 움직임을 넣은 컷이다. 확대만 되어 있으면(가로 영상을 세로로 채운 것 등) 화면 맞춤으로 보고 그 위에 곱한다.
        touched = bool(s.get("common_keyframes")) and not mine.get("zoom")
        frame = mine.get("frame") or (clip.get("scale") or {}).get("x", 1.0)
        r = {}
        if plan.get("zoom") and not touched:
            dur = (c["t1"] - c["t0"])
            if c["n"] in calm:
                base, pts = z["wide"], [(0.0, z["wide"]), (dur, z["calm_push"])]
            else:
                base = z["wide"] if c["n"] % 2 else z["close"]
                pts = [(0.0, base * z["pop"]), (min(z["pop_time"], dur / 2), base), (dur, base)]
            s["clip"] = dict(clip, scale={"x": base * frame, "y": base * frame})
            s["common_keyframes"] = scale_keyframes(s, c["speed"], [(o, v * frame) for o, v in pts])
            r.update(zoom=True, frame=frame)
        elif plan.get("zoom"):
            skipped.append(c["n"])
        if plan.get("volume") and (abs(s.get("volume", 1.0) - 1.0) < 1e-6 or "volume" in mine):
            s["volume"] = plan["volume"]
            r["volume"] = plan["volume"]
        if r:
            rec_new["cuts"][s["id"]] = r
    if skipped:
        say("이미 손댄 컷이라 확대를 건너뜀:", skipped)

    backup = os.path.join(work, "백업", time.strftime("%m%d_%H%M%S"))
    while os.path.exists(backup):
        backup += "_"
    os.makedirs(backup)
    body = json.dumps(info, ensure_ascii=False, separators=(",", ":"))
    targets = [os.path.join(folder, "draft_info.json")] + glob.glob(os.path.join(folder, "Timelines", "*", "draft_info.json"))
    targets += glob.glob(os.path.join(folder, "**", "template-2.tmp"), recursive=True)
    for p in targets:
        shutil.copy2(p, os.path.join(backup, os.path.relpath(p, folder).replace("/", "__")))
        open(p, "w", encoding="utf-8").write(body)
    json.dump(rec_new, open(rec_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    say("자막 %d줄, 글 %d개, 트랙 %d개를 넣음. 원래 파일: %s" % (
        len(plan["lines"]), sum(len(ln) for ln in lanes), len(rec_new["tracks"]), backup))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find")
    p.add_argument("--limit", type=int, default=8)
    for name in ("prep", "plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("project")
        p.add_argument("--work")
        if name == "prep":
            p.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
        if name == "plan":
            p.add_argument("--style", default="soun")
            p.add_argument("--calm-cuts", default="", help="감성 구간 컷 번호(쉼표로). 명조 글꼴 + 천천히 다가감")
            p.add_argument("--pause", type=float, default=0.3, help="이만큼(초) 소리가 끊기면 줄을 나눈다")
            p.add_argument("--force", action="store_true", help="plan.json을 덮어쓴다")
            p.add_argument("--script", help="말한 대본 글 파일. 있으면 자막 글을 대본 글로 쓴다(시각은 받아쓰기)")
        if name == "apply":
            p.add_argument("--plan")
            p.add_argument("--dry", action="store_true")
            p.add_argument("--text", choices=("stop", "keep", "replace"), default="stop",
                           help="이 도구가 넣지 않은 글자 트랙이 있을 때: 멈춤 / 두고 더함 / 지우고 넣음")
    a = ap.parse_args()
    {"find": cmd_find, "prep": cmd_prep, "plan": cmd_plan, "apply": cmd_apply}[a.cmd](a)


if __name__ == "__main__":
    main()
