# 김비서 본체 (app)

마이크 → 귀(받아쓰기 서버) → 두뇌(OpenAI 호환) → 도구 → 목소리(말하기 서버) → 스피커로 이어지는 대화 흐름입니다.
모든 것이 이 PC 안(127.0.0.1)에서 돕니다. 바깥 두뇌(GPT·클로드·내 AI 주소)를 고르면 대화 글만 그 서버로 갑니다.

## 실행

    python -m app.main serve [--settings 설정.json]       # 본체(기본 127.0.0.1:8870) — 화면도 같은 주소(/)
    python -m app.shell [--settings 설정.json] [--start-body]   # 김비서 창(pywebview·엣지 WebView2)으로 화면 열기
    python -m app.main script 대본.json --out 결과폴더      # 시험: 마이크 대신 wav 대본
    pythonw -m app.launcher [--settings 설정.json]          # 실행기(바탕화면 '김비서' 아이콘이 부르는 것) — 창 하나로 전부 켜고, 창을 닫으면 끔
    python -m app.launcher start --no-window [--only 두뇌,귀] · stop · status

실행기(`app/launcher.py`)는 설정의 `실행` 칸을 보고 두뇌(llama-server, `127.0.0.1:8880`)·귀·목소리·본체·펫을 순서대로 창 없이 켜고,
준비될 때까지 기다린 뒤 김비서 창을 엽니다. 켠 프로세스는 `<자료>\run\launcher.json` 에 PID·실행 파일·시작 시각으로 적고,
끌 때는 그 셋이 모두 맞는 것만 끕니다(이름으로 끄지 않음). 본체·목소리·귀에는 `--parent_pid` 를 넘겨 실행기가 사라지면 같이 꺼집니다.
설정 화면의 '지금 다시 켜기'는 다시 켜야 하는 항목(목소리·귀)만 다시 켭니다. 그래픽 메모리가 모자라면 두뇌는 CPU 로 켭니다.

serve 가 여는 주소(이 PC 안에서만, Host·Origin·형식 검사):

| 주소 | 하는 일 |
|---|---|
| POST/PATCH `/api/offer` | 대화 연결(WebRTC). 한 번에 한 기기 — 새 연결이 오면 앞 대화를 끝냄 |
| POST `/api/text` | 글 입력 `{"text": "..."}` — 같은 두뇌로, 말하는 중이면 끊고 답함 |
| GET `/api/status` | 대화 중인지·이름·호칭·끼어들기 감도·마이크 처리(메아리 지우기)·다시 켜야 할 설정·캐시 가드·펫 |
| GET `/` · `/ui/<파일>` | 화면(처음 화면·대화·기억·설정). 스크립트는 파일로만(CSP `script-src 'self'`) |
| GET `/api/events` | 화면에 보낼 사건(SSE): 상태·내 말·비서 말·도구·이름 바뀜·설정 바뀜 |
| GET/POST `/api/settings` | 설정 보기 · 바꾸기 `{"바꿀것": {...}}` — 검사 → 저장 → 바로 반영, 반영 시점을 돌려줌 |
| POST `/api/secret` | 열쇠 저장·지우기 `{"이름": "url|openai|claude", "값"}` — 설정 파일·기록에 값이 남지 않음 |
| GET `/api/update` · POST `/api/update/check`·`/download`·`/apply`·`/seen`·`/page` | 업데이트: 상태 · 새 판 확인 · 받기(서명·sha256·파일마다 확인) · 바꾸기(`installer/updater.py` 를 따로 띄움) · 지난 결과 봤음 · 받는 곳 열기 |
| GET `/api/system` · POST `/api/brain/test` | 사양 보기·추천 구성 · 두뇌 연결 시험(한 문장 + 도구 하나) |
| POST `/api/ear/hear` · `/api/name/learn` · `/api/name/check` | 이름 세 번 불러 보기(받아쓰기 → 비슷한 이름) · 이름 경고 |
| POST `/api/voice/sample` · `/api/client` | 목소리 견본 · 화면 마이크 처리 상태 알림(getSettings 결과, 본체 기록에 남김) |
| GET `/api/memory` · POST `/api/memory/delete` | 기억 보기 · 지우기 `{"id"}` / `{"day"}` / `{"all": true}` |
| POST `/api/shutdown` | 끄기(자료 폴더 `secrets\shutdown_secret.txt` 값을 머리글 `X-KimBiseo-Shutdown` 에) |

## 설정

`app/config/default.json` 이 기본값 전부이고, 사용자 설정(`%APPDATA%\KimBiseo\settings.json`)은 바꾼 것만 덮어씁니다.

- 이름·호칭·말투: `비서.이름`(기본 김비서) · `비서.별칭` · `비서.말투` · `비서.성격` · `사용자.호칭`.
  이름만 바꾸고 별칭을 그대로 두면 옛 이름의 별칭은 쓰지 않습니다(옛 이름으로 깨지 않게).
- 두뇌: `두뇌.방식` = `local`(이 PC 의 llama-server) · `url`(내 AI 주소) · `openai` · `claude`.
  `두뇌.모드` = `빠른`(생각 끔, 기본) · `꼼꼼`(생각 켬). 열쇠는 설정 파일에 두지 않습니다 —
  `core/keystore.py`(환경변수 `KIMBISEO_KEY_<이름>` 또는 자료 폴더 `secrets\<이름>.bin`, 윈도우 계정 암호화).
- 펫: `펫.옷_받기`(처음 화면에서 '받을게요'를 고르면 true → 펫이 기본 옷을 받음) · `펫.옷목록_주소`(설치 때 `installer/install_config.json` 값) · `펫.옷`.
- 실행: `실행.*`(설치가 채움: 두뇌 실행 파일·모델·장치, 귀·목소리 파이썬, 펫 실행 파일·폴더, 준비 기다림).
- 도구: `도구.묶음`(기본 `["basic"]`) · `도구.끄기`. 꺼진 도구는 지시문 안내에서도 빠집니다.

## 화면(app/ui)과 반영 시점

- 처음 켜면(`처음설정.끝` 이 false) 처음 화면: 사양 → 펫(성별) → 이름·호칭 → 두뇌 → 목소리 → 마이크·스피커 → 부르는 방식·이름 연습 → 끝.
  고른 값은 마지막 '시작하기'에서 한 번에 저장합니다. 열쇠만 넣는 즉시 `/api/secret` 으로 따로 저장합니다.
- 선택지(호칭 단추·펫·목소리·두뇌 종류·끼어들기 감도 등)는 `app/config/choices.json`.
- 설정을 저장하면 같은 cfg 를 다시 읽어(`config.reload_into`) 대화가 바로 봅니다. 항목마다 반영 시점이 있습니다(`core/settings_api.py` FIELDS):
  바로(이름·별칭·호칭·말 빠르기·끼어들기 감도·이름 부르기 등) · 다음 대화부터(두뇌·말투 등) · 다시 켜야(목소리 엔진·장치, 받아쓰기 장치) · 펫.
  이름을 바꾸면 깨우는 이름·자기소개가 지금 대화에서도 바로 바뀝니다.
- 끼어들기 감도 `대화.끼어들기_감도` = 0.3(보통, 지금까지의 기본값) · 0.4 · 0.5(아주 시끄러운 곳) → 세부 다섯 값(`config.BARGE_LEVELS`).
- 마이크는 echoCancellation·noiseSuppression·autoGainControl 을 켜서 열고, `getSettings()` 로 실제로 켜졌는지 확인해
  화면에 보이고 본체에 알립니다(꺼져 있으면 빨간 경고). `/?aec=off` 는 시험용(처리를 끈 채 열어 경고 확인).
- 사양 추천(`core/sysinfo.py`): 그래픽 메모리 8GB 이하면 목소리는 윈도우 음성(김비서 목소리는 고를 수 있으나 경고), 12GB 이상이면 모두 그래픽카드.

## 캐시(첫 글자 빠르게)

- 지시문(이름·말투·도구 안내) + 도구 정의 + 기억 블록을 고정 순서로 맨 앞에 두고, 바뀌는 것(시각·새 차례)은 뒤에 둡니다.
  지금 시각은 사용자 말 끝 꼬리표로 한 번 붙여 대화에 그대로 남겨, 다음 차례에도 앞부분이 같습니다.
- 로컬(llama-server): `cache_prompt` 켬, 대화마다 같은 칸(`두뇌.슬롯`, 기본 0), 대화 시작 때 앞부분을 미리 읽힘.
  `--cache-reuse` 는 쓰지 않는 것을 전제로 합니다(쓰면 아래 가드가 지나치게 조심할 수 있음).
- 캐시 오염 가드(`core/brain.py` CacheGuard): 응답 첫 조각의 `timings.cache_n` 이 '이번 요청과 지난 요청들의 공통 앞부분
  (같은 대화를 이어 쓰면 + 그때 만든 토큰 수)'보다 크면, 그 답을 버리고 경고를 남긴 뒤 캐시를 끈 채 다시 묻습니다.
  답 글은 검사가 끝난 뒤에야 목소리로 갑니다.
- GPT: `prompt_cache_key` + 고정 앞부분. 클로드: pipecat 의 `enable_prompt_caching`(cache_control).

## 기억(전부 이 PC 자료 폴더 `기억\` 안)

- `facts.json` 아는 사실(말로 '기억해' + 대화가 끝나면 두뇌가 골라 자동으로) · `diary\` 일기 · `archive.jsonl` 대화 원문 ·
  `context.json` 이어가기(최근 차례 + 요약, `문맥.이어가기_시간` 안에 다시 켜면 이어짐).
- 비밀번호·카드번호 같은 값은 가려서 저장합니다(`core/redact.py`).

## 도구 묶음 만들기

`app/tools/<묶음>/tools.json`(도구 정의, 도구마다 선택 `"안내"` 글) + `handlers.py`(`HANDLERS = {이름: async 함수(ctx, args)}`).
모든 호출은 같은 겉싸개(불리언 정리·멈춤말·상한·반복·폭주 멈춤·먼저 한마디·결과 길이)를 지납니다 — `tools/registry.py`.

되돌리기 어려운 도구(지우기·보내기·결제 같은 것)는 tools.json 의 도구 항목에 `"확인"` 을 붙입니다 —
`"확인": "'{what}' 을(를) 지울까요?"`(늘 물음) 또는 `"확인": {"글": "...", "조건": {"all": true}}`(인자가 조건과 같을 때만 물음).
그러면 실행 전에 대화 중인 화면(PC 창 또는 폰 앱)에 '실행할까요?' 단추가 뜨고, '실행'을 눌러야 실행합니다(45초 안에 답이 없거나 화면이 없으면 실행 안 함).
`phone` 묶음은 폰 앱으로 대화할 때만 붙습니다(폰에서 길안내·전화/문자 화면·앱 열기). 폰 대화에서 PC 도구(`pc_action`·`type_text`)는 설정 `폰.PC조작_허용` 을 따릅니다.

## 시험

    python -m tests.unit.test_body          # 단위 시험(소리·두뇌 없이)
    python -m tests.unit.test_settings      # 설정 값 검사·반영 시점·끼어들기 감도·사양 추천
    python tests/e2e/fake_brain.py --port 18990   # 가짜 두뇌(도구 호출·글로 쓴 호출·캐시 오염 흉내)
    python tests/e2e/fake_pet.py --port 17961 --log 펫.jsonl
