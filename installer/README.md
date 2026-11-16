# installer — 설치

사용자는 저장소 맨 위의 `설치.bat` 하나만 두 번 누릅니다. 까만 창 없이 설치 창이 뜨고, '설치' 단추 하나로 끝까지 갑니다.

| 파일 | 하는 일 |
|---|---|
| `install.ps1` | 설치 창(WinForms). 사양 보기 · 설치 위치 · '설치' · 실패하면 쉬운 이유 + '다시 하기' · '김비서 켜기' · '기록 보기'. 일꾼을 창 없이 띄우고 상태 파일만 읽음 |
| `worker.ps1` | 일꾼 1: 공식 파이썬(embeddable, 판 고정 + sha256 + python.org md5) 을 받아 `<설치 폴더>\runtime\python-app` 에 풀고 pip 를 넣은 뒤 `setup_core.py` 를 창 없이 돌림 |
| `setup_core.py` | 일꾼 2(설치 본체): 사양 → 프로그램 파일 → 파이썬 부품 → 두뇌 프로그램(llama.cpp) → 모델 → 펫(electron) → 아이콘·앱 목록·설정. 이미 있는 것은 건너뜀 |
| `plan.py` | 사양별 자동 구성(아래 표). 가짜 사양 환경변수로 시험 가능 |
| `runtimes.json` | 공식 파이썬·pip·setuptools·llama.cpp(엔비디아 CUDA 13/12·불칸·CPU)·electron 의 판·주소·크기·sha256 |
| `locks/*.json` | 파이썬 부품 잠금: 이름·판·주소·sha256(본체 `app`, 음성 `voice-cuda`/`voice-cpu`). 설치는 이 주소에서 직접 받아 sha256 을 확인한 뒤 `pip --no-index --require-hashes` 로만 넣음 |
| `requirements/*.txt` | 잠금을 만드는 원래 목록. 잠금은 `make_lock.py`(개발자 도구)로 다시 만듦 |
| `models.json` · `get_models.py` | 모델 목록(고정 판·크기·공식 해시)과 받기(이어 받기·다시 시도·진행·받은 뒤 해시 확인·확인 기록) |
| `install_config.json` | 설치 때 정하는 값. `packs_catalog` = 펫 옷 목록 주소 한 줄(공개판 = 옷 저장소 kimbiseo-outfits 의 `outfits.json`, https, `pet/config.json` 의 `allowed_hosts` 안) |
| `updater.py` | 업데이트 바꾸기 일꾼(표준 라이브러리만). 본체가 새 판을 받아 서명·sha256 을 확인한 뒤 이 파일을 `install\update\updater_run.py` 로 복사해 띄움 → 김비서 끄기(기록된 PID 만) → `src` 만 바꿔 끼우기 → 문법·불러오기·본체 켜짐 검사 → 안 되면 예전 판으로 되돌림 → 다시 켜기. 다시 켠 뒤 실행기가 오류로 꺼져도 되돌림 |
| `uninstall.ps1` | 지우기(시작 메뉴 '김비서 제거' · 윈도우 '앱 및 기능'). 자기 설치 폴더·아이콘·앱 목록·이 펫이 만든 파일 연결만 지우고, 대화 기억·설정은 물어봄 |

## 사양별 자동 구성

두뇌(0.1.4~): 이 PC 에 클로드 코드(`claude auth status`)·Codex(`codex login status`)가 로그인돼 있으면 그것을 기본 두뇌로
(`claude_cli` → `codex_cli` 순) 하고 Gemma·llama.cpp 는 받지 않습니다. 없을 때만 아래 표의 '이 PC' 두뇌
(Gemma 4 E4B 무검열 판 `gemma-4-E4B-it-abliterated-Q4_K`, huihui-ai 원 저장소에서 고정 판·sha256 으로 직접 받음. `--gemma E2B`(설치 창 `-Gemma E2B`, 설정 '두뇌 바꾸기 → Gemma 판')면 작은 판 `gemma-4-E2B-it-abliterated-Q4_K` 약 3.4GB). 받아쓰기(귀) 장치는 설정 '목소리 → 받아쓰기 장치'(자동·그래픽카드·CPU)에서 바꿈 — CPU 받아쓰기는 한 문장 7~8초라 저절로 CPU 로 바꾸지는 않음.
이미 '내 PC(Gemma)'로 쓰던 사람의 업데이트는 두뇌를 바꾸지 않습니다. 판별 근거는 install.log 의 `판별:` 줄.

| 이 PC | 두뇌(구독 없을 때) | 귀 | 목소리 |
|---|---|---|---|
| 엔비디아 그래픽 메모리 9GB 이상 | 이 PC(Gemma, 그래픽카드) | whisper-large-v3-turbo(그래픽카드) | 김비서 목소리(Qwen3-TTS, 그래픽카드) |
| 6~9GB(8GB 급) | 이 PC(Gemma, 그래픽카드 — 남은 메모리 모자라면 CPU) | 그래픽카드 | 김비서 목소리(켤 때 3.3GB 이상 남아야 — 아니면 윈도우 음성) |
| 6GB 미만 | 바깥 AI(처음 화면에서 고름) | 그래픽카드 | 윈도우 음성 |
| 엔비디아 없음 | 바깥 AI(처음 화면에서 고름) | 작은 귀 whisper-small(CPU) | 윈도우 음성 |
| 엔비디아 없음 + '그래도 이 PC 에서 두뇌 돌리기' | 이 PC(다른 그래픽카드면 불칸, 없으면 CPU) | whisper-small(CPU) | 윈도우 음성 |

설정 '두뇌 바꾸기'의 Gemma 설치·삭제는 `setup_core.py gemma-install` / `gemma-remove` 를 본체가 따로 띄워 합니다.

엔비디아 드라이버 580 이상이면 llama.cpp CUDA 13 판, 그보다 옛것이면 CUDA 12 판. 디스크가 모자라면 시작 전에 멈춥니다.

## 받기가 안 될 때(0.1.12~)

설치 때 받는 것은 전부 `get_models.download()` 를 지납니다.

- **이어 받기·다시 시도**: 끊기면 받은 만큼(`.part`)에서 이어 받습니다. 받아지는 동안은 계속 잇고(기다림 2·4·8…초),
  거의 못 받은 시도가 5번 이어지면 그만둡니다. `429`(잠시 뒤 다시)는 서버가 말한 만큼 기다립니다.
- **윈도우 내려받기로 대신 받기**: 파이썬으로 안 되면 윈도우에 든 `curl.exe`, 그것도 안 되면 파워셸(`Invoke-WebRequest`)로 받습니다
  (받은 뒤 sha256 으로 확인하는 파일만). 인증서 확인 실패는 다시 해도 같으므로 바로 넘어갑니다.
  까닭: 파이썬은 윈도우 인증서 저장소에 **이미 있는** 뿌리 인증서만 읽는데, 윈도우는 뿌리 인증서를 처음 쓸 때 받아 넣습니다.
  깃허브 쪽 뿌리(USERTrust ECC · ISRG Root X1)를 아직 받은 적 없는 PC 에서는 파이썬만 `CERTIFICATE_VERIFY_FAILED` 로 실패합니다
  — 두뇌를 구독(클로드 코드·Codex)으로 쓰는 PC 는 깃허브에서 받는 첫 단계가 '펫'이라, 0.1.11 까지는 그 단계에서 설치가 멈췄습니다.
  프록시 자동 설정(PAC)·보안 프로그램 때문에 파이썬 연결만 막힌 PC 도 이 길로 받습니다.
- **깨진 파일**: 받은 파일이 원본과 다르면(sha256) 지우고 한 번은 저절로 새로 받습니다.
- **실패 안내**: 원인(인증서·주소를 못 찾음·응답 없음·끊김·막힘·거절 403·없음 404·디스크·파일 쓰기)을 쉬운 말로 보여 주고,
  `install.log` 에 `진단:` 줄(윈도우 판·원인·써 본 방식·프록시 설정 여부·curl 유무·디스크 여유·받는 곳 이름)을 남깁니다.
- **'펫' 단계는 실패해도 설치를 끝냅니다**: 김비서(대화)는 먼저 쓰고, 펫은 나중에 넣습니다.
  설치 창에 '펫 다시 설치' · '받아 둔 파일로'(브라우저로 직접 받은 압축 파일을 고름 — 크기·sha256 이 맞아야 씀) ·
  '직접 받을 주소 복사' · '기록 폴더 열기' 가 생기고, 김비서 설정 → 펫 → '펫 프로그램' 에도 같은 단추가 있습니다.
  둘 다 `setup_core.py pet-install [--file <압축 파일>]` 을 부릅니다.
- 문제 해결용 환경변수 `KIMBISEO_DOWNLOADER` = `python` | `curl` | `powershell` 로 받는 방식을 하나로 정할 수 있습니다.
- 깃허브에서 받는 주소는 모두 고정 주소(`releases/download/<판>/<파일>` · `raw.githubusercontent.com`)라 깃허브 API 의
  시간당 횟수 제한(로그인 없이 60번)에 걸리지 않습니다.

펫 옷(첫 실행 때 약 150~170MB)도 0.1.12 부터 끊기면 이어 받고 다시 시도합니다(`pet/packs.js download`).

## 받는 곳(정해 둔 https 호스트만)

www.python.org · files.pythonhosted.org · download.pytorch.org(download-r2) · github.com(+githubusercontent) · huggingface.co(+hf.co) ·
펫 옷은 `install_config.json` 의 주소. PyAV(av)는 설치판에 넣지 않고, 본체 부품(aiortc)이 필요로 할 때 사용자 PC 가 PyPI 에서 직접 받습니다.

## 개발자용

```
python installer/plan.py                                   # 이 PC 사양 → 구성
set KIMBISEO_FAKE_GPU=RTX 4060:8188 & python installer/plan.py   # 가짜 사양(none · 이름:MiB)
python installer/setup_core.py install --prefix <폴더> --data <폴더> --status <파일> --dry-run --no-shortcuts --no-register
                                                           # 받지 않고 주소·크기만 HEAD 로 확인 + 설정 파일만 씀
python installer/get_models.py list | get [--all] | check <모델>
python installer/make_lock.py requirements/app.txt locks/app.json      # 잠금 다시 만들기(받지 않음, pip --dry-run)
python -m tests.unit.test_installer                        # 단위 시험(받기·설치 없음)
python -m tests.unit.test_install_download                 # 받기 단위 시험(이 PC 안 임시 서버가 끊고·거절하고·깨진 파일을 줌)
python installer/setup_core.py pet-install --prefix <폴더> --data <폴더> [--file <받아 둔 electron zip>]   # 펫 실행 틀만 다시
```

설치하면: `<설치 폴더>`(기본 `%LOCALAPPDATA%\KimBiseo`) = 프로그램·파이썬·모델·두뇌 프로그램·펫 틀 ·
`<자료 폴더>`(기본 `%APPDATA%\KimBiseo`) = 설정·대화 기억·열쇠·펫 옷·기록(`logs\install.log`).

## 업데이트(설치한 뒤)

`<설치 폴더>\src` 만 새 판으로 바뀝니다. `runtime`(파이썬·두뇌 프로그램·펫 틀)·`models`·자료 폴더는 그대로입니다.
예전 판은 `<설치 폴더>\install\update\previous` 에 한 판 남고, 되돌린 실패 판은 `failed_<판>_<시각>` 에 남습니다.
기록 = `<자료 폴더>\logs\update.log` · 결과 = `<자료 폴더>\update\result.json`.
`installer/locks`·`runtimes.json`·`models.json` 이 바뀌는 판은 코드만 바꿔서는 안 되므로, 앱이 '새 설치 파일로 설치' 를 안내합니다
(같은 설치 폴더에 다시 설치하면 받은 것은 건너뛰고 대화 기억·설정은 남습니다).
