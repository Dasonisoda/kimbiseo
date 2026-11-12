# voice — 귀(받아쓰기)·목소리 서버

둘 다 **이 PC 안(127.0.0.1)** 에서만 듣습니다. 같은 파이썬 환경(음성용) 하나로 돕니다.

| 서버 | 기본 포트 | 엔진 | 그래픽카드 없을 때 |
|---|---|---|---|
| 귀 `ear_server.py` | 8872 (TCP) | whisper-large-v3-turbo | CPU 로 돌지만 느림(한 마디 십몇 초) |
| 목소리 `tts_server.py` | 8871 (HTTP) | Qwen3-TTS 0.6B 김비서 목소리 | 윈도우 기본 음성으로 바로 넘어감 |

## 켜기

```
python voice/ear_server.py  [--settings 설정.json] [--device auto|cuda|cpu] [--port 8872]
python voice/tts_server.py  [--settings 설정.json] [--device auto|cuda|cpu] [--engine qwen|windows] [--port 8871]
```

- 설정은 `%APPDATA%\KimBiseo\settings.json`(없으면 기본값). 항목과 기본값은 `config.py` 의 `DEFAULTS`.
- 모델은 `installer/get_models.py get` 으로 `%LOCALAPPDATA%\KimBiseo\models\` 에 받아 둡니다. 켤 때는 인터넷에 묻지 않습니다(`모델.오프라인`).
- `--device auto` 는 그래픽 메모리가 넉넉할 때만 그래픽카드를 씁니다(귀 2.2GB, 목소리 3.3GB 남아 있어야 — 목소리는 이보다 적게 남으면 끊기는 대신 윈도우 기본 음성).
- 목소리는 **참고음성**(김비서 목소리 샘플)이 있어야 김비서 목소리로 말합니다. 없으면 윈도우 기본 음성으로 말하고
  `/status` 의 `fallback_reason` 에 이유가 나옵니다. 참고음성 폴더 = 설정 `목소리.참고음성_폴더`
  (그 안에 `참고목록.json` = `{"기본": {"wav": "파일.wav", "text": "그 파일에서 하는 말"}}`).
- 실행 관리가 켤 때는 `--parent_pid` 를 주면 실행 관리가 끝날 때 같이 끝납니다.

## 귀 규약 (TCP, 한 줄 JSON)

```
요청  {"op":"asr","id":1,"n":<바이트 수>,"max_tokens":선택,"quiet":선택}\n  + int16 16kHz 모노 PCM
응답  {"id":1,"text":"...","sec":계산 초,"rms_db":소리 크기,"audio_sec":소리 초}\n
      {"op":"ping"} → {"type":"pong"}   ·   {"op":"status"} → 장치·모델·그래픽 메모리
```
한 번에 60초까지(`귀.최대_초`). `max_tokens` 는 이름 부르기 확인처럼 짧은 조각에서 받아쓰기 길이를 묶을 때 씁니다.

## 목소리 API (HTTP, JSON 만, 웹페이지발 요청 거절)

| 주소 | 하는 일 |
|---|---|
| `POST /tts_stream` | 만들어지는 대로 WAV 조각 전송(chunked). `"raw": true` = 본체용(글 정리 없이, 앞 무음 자르고, `pace`·`session` 으로 재생 시계 맞춤, 연결을 끊으면 바로 멈춤) |
| `POST /tts` | WAV 한 덩어리(캐시됨) |
| `POST /tts_lip` | WAV + 펫 입 모양 시간표 |
| `POST /read` | 글 정리 결과만(숫자·부품 이름 읽기) |
| `GET /status` | 엔진·장치·그래픽 메모리·바쁨·예비로 넘어간 이유 |

- 공통 입력: `text`(500자까지) · `emotion`(목소리에 없는 감정은 기본) · `seed` · `voice` · `speed`(0.5~2.0)
- 빠르기: 윈도우 음성은 서버가 바로 빠르게 읽습니다. 김비서 목소리는 `"apply_speed": true` 이고 환경에 PyAV 가 있으면
  서버가 줄여서 보내고, 아니면 머리 `X-Speed-Applied: 0` 으로 알려 받는 쪽(본체)이 `speech_rate.py` 로 줄입니다.

## 파일

| 파일 | 하는 일 |
|---|---|
| `config.py` | 설정 읽기(기본값 + 사용자 설정), 경로 풀기, 장치 고르기 |
| `ear.py` · `ear_server.py` | whisper 받아쓰기 · 귀 서버 |
| `tts_engine.py` · `tts_server.py` | Qwen3-TTS 음성 복제(빠른 스트리밍) · 목소리 서버 |
| `sapi_engine.py` | 윈도우 기본 음성 예비 엔진(그래픽카드·추가 설치 없음) |
| `text_norm.py` · `pronunciation.tsv` | 글 정리(숫자·날짜·부품 이름을 소리 나는 대로) · 기본 발음 사전 |
| `lipsync.py` | 소리만으로 펫 입 모양 시간표 |
| `speech_rate.py` | 음 높이는 그대로 두고 말 빠르기만 바꿈(PyAV) |
| `voice_check.py` | (선택, 기본 꺼짐) 만든 소리가 참고음성과 덜 닮으면 다시 만들기 |
| `voices.json` · `phrases.txt` | 목소리 목록 · 켤 때 미리 만들어 둘 말 |

## 개인정보

- 로그(`%APPDATA%\KimBiseo\logs\ear.log`, `voice.log`)에는 기본으로 **글자 수만** 남깁니다. 받아쓴 글·읽은 글을 남기려면
  `귀.로그_글_남기기`·`목소리.로그_글_남기기` 를 켜세요. 소리는 저장하지 않습니다(목소리 캐시는 김비서가 한 말만).
