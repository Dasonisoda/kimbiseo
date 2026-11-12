내 PC 두뇌 서버(llama-server) 띄우기와 프로필을 둘 곳입니다.

- `bench_brain.py` — OpenAI 호환 두뇌 주소의 첫 글자까지 시간·생성 속도를 잽니다(표준 라이브러리만).
  `python bench_brain.py --base-url http://127.0.0.1:8880/v1 --out 속도.json` · 긴 문맥은 `--long 6000`
- 도구 고르기 시험은 `../tests/brain_eval/` 에 있습니다.
