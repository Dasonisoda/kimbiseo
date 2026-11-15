공개판 시험을 둘 곳입니다 — 시험 자료는 가짜 값만 씁니다.

- `unit/test_body.py` — 본체 단위 시험(소리·두뇌 없이). `python -m tests.unit.test_body`
- `unit/test_update.py` — 업데이트 단위 시험(서명·꾸러미 확인·바꿔 끼우기·되돌리기). cryptography 가 있는 파이썬으로 `python -m tests.unit.test_update`
- `unit/test_installer.py` — 설치·실행기 단위 시험(받기·설치 없음). `python -m tests.unit.test_installer`
- `unit/test_settings.py` — 설정 화면 단위 시험(값 검사·반영 시점·끼어들기 감도·사양 추천). `python -m tests.unit.test_settings`
- `unit/test_voice_gender.py` — 성별→목소리 단위 시험(자동 연결·직접 고정·자산 없음 대체·voices.json 보존). `python -m tests.unit.test_voice_gender`
- `unit/test_voice_outfit.py` — 옷→목소리 단위 시험(입은 옷으로 고르기·'옷에 맞춤(자동)' 설정·모르는 목소리는 기본으로·펫에 옷 묻기). `python -m tests.unit.test_voice_outfit`
- `e2e/fake_brain.py` — 가짜 두뇌(OpenAI 꼴 + llama-server 꼴 `/apply-template`·`/tokenize`). 규칙으로만 답함.
  `--text-tools`(도구 호출을 글로 씀) · `--trip N`(캐시 오염 흉내) · `--require-key 환경변수`(바깥 두뇌 흉내, 열쇠 값은 기록 안 함)
- `e2e/fake_pet.py` — 본체가 펫에 보내는 신호를 받아 기록만 하는 가짜 펫
- `brain_eval/` — 두뇌 모델 고르기 시험(3단계)
