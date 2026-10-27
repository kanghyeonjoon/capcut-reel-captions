# capcut-reel-captions

이 저장소는 Claude Code 스킬이다. 컷 편집을 마친 캡컷(CapCut, 맥) 세로 영상에 릴스용 글자를 넣는다. 컷 편집은 건드리지 않는다.

넣는 것:
- **자막:** 2~4단어씩 한 줄. 숫자는 파란색으로 강조하고, 감성 구간은 명조로 쓴다.
- **첫 화면 제목**
- **마지막 계정 소개 글**

## 하는 일

1. **받아쓰기:** 캡컷 프로젝트에서 컷 목록을 읽는다. 편집된 그대로의 소리를 만들어 받아쓴다(Apple SpeechAnalyzer).
2. **자막 초안:** 받아쓴 말을 짧은 줄로 나눠 `plan.json` 초안을 만든다. 그다음 Claude가 다듬는다.
   - 잘못 들은 말을 고친다.
   - 뜻 단위로 다시 나눈다.
   - 감성 구간을 정하고 제목을 쓴다.
3. **캡컷 파일에 쓰기:** 캡컷에서 프로젝트를 닫은 뒤 쓴다.
   - 일반 텍스트로 쓰기 때문에 내보낼 때 Pro를 요구하지 않는다.
   - 컷마다 넓게/가깝게 확대 리듬을 주고, 말소리를 키운다.
4. **확인:** 캡컷에서 열어 확인한다. 내보내기는 사람이 한다.

자세한 순서는 [SKILL.md](SKILL.md)에 있다.

## 설치

```bash
git clone <이 저장소 주소> ~/.claude/skills/capcut-reel-captions
```

준비물:
- macOS 26 이상
- Xcode 명령줄 도구(`swiftc`)
- python3
- 캡컷 맥 9.5

Swift 도구는 처음 쓸 때 `scripts/bin/`에 만들어진다.

## 직접 쓰기

```bash
R=~/.claude/skills/capcut-reel-captions/scripts/reel.py
python3 $R find                    # 최근 캡컷 프로젝트
python3 $R prep 1027               # 편집본 소리 받아쓰기
python3 $R plan 1027 --calm-cuts 10,11
# ~/영상편집/1027_자막/plan.json 다듬기
python3 $R apply 1027 --dry        # 확인만
python3 $R apply 1027              # 캡컷에서 닫은 뒤
```

## 파일

| 파일 | 내용 |
|---|---|
| `SKILL.md` | Claude가 따르는 순서와 판단 기준 |
| `scripts/reel.py` | find / prep / plan / apply |
| `scripts/timeline_audio.swift` | 컷 편집된 그대로 소리 이어 붙이기 |
| `scripts/transcribe.swift` | 한국어 받아쓰기(낱말 시각 포함) |
| `scripts/envelope.swift` | 20ms마다 소리 크기 |
| `scripts/sheet.swift`, `probe.swift` | 장면 격자 한 장, 길이·크기 재기 |
| `assets/styles/soun.json` | 기본 스타일(글꼴, 크기, 위치, 색, 확대, 소리) |
| `assets/text_template.json` | 캡컷 일반 텍스트 조각 본 |
| `references/` | 캡컷 파일 구조와 함정, 레퍼런스 릴스 분석 |
