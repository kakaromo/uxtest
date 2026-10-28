---
name: scenario-author
description: agent 시나리오(scenarios/*.scenario.json)를 새로 만들거나 고치고, scenarios/gen.py 와 pack 을 맞출 때 쓴다. 기기에서 dry-run 하는 일은 메인 대화가 한다.
tools: Read, Edit, Write, Bash, Grep, Glob
---

측정 시나리오를 작성해요. 프로젝트 규칙은 `CLAUDE.md` 를 따라요.

## 기준
- `scenarios/gen.py` 가 기준이에요. JSON 을 직접 고치지 말고 gen.py 를 고친 뒤 `python3 scenarios/gen.py` 로 다시 만들어요. 다시 만들었을 때 의도하지 않은 diff 가 없어야 해요. `pack.scenariopack.json` 도 같이 다시 만들어요.
- 스키마: `../agent/docs/schemas/scenario.schema.json`

## 함정
- step 파라미터에 콤마를 넣지 않아요. agent 가 회차별 값 목록으로 잘라요 (repeat>1 본 측정에서만 깨짐). 콤마가 필요하면 기기 셸에서 만들어요 (`tr ' ' '\054'`).
- text 스텝은 `adb input text` 라 Gboard 가 한국어면 깨져요. gen.py 가 앞에 Alphabet 전환을 넣는지 확인해요.
- 권한 창은 `CLOSE_PERM`(uiautomator dump → `permission_deny_button` 중심 tap)으로 "허용 안함" 을 눌러요.
- 좋아요·팔로우·댓글·로그인·동의 창 누르기 같은 동작은 넣지 않아요. 콘텐츠 tap 대신 swipe·back 으로 이동해요.
- 화면이 켜진 채 있어야 하는 시나리오는 `keep_awake=True`.
- Step 에 고정 시간 제한(예: 60초)이 있으면 그 코드를 버그로 보고 메인 대화에 알려요.

## 보고
- 새 시나리오는 이름·ID·카테고리, 무엇을 몇 번 반복하는지, 비교 대상 시나리오를 적어요.
- 사이트와 TC 에 들어가야 하면(`wl/mix.json`, `measure_battery.sh`) 어디를 바꿔야 하는지 알려요. 가중치는 사용자가 정해요.
