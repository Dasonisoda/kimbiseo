# Qwen3-TTS GGUF 실행 부품(llama.cpp + ONNX) — 그래픽카드 종류를 가리지 않는 김비서 목소리 길(라데온·인텔·내장·CPU).
#   원본: HaujetZhao/Qwen3-TTS-GGUF (MIT, 커밋 74feb581bc8c) 의 qwen3_tts_gguf/inference 중 음성 복제에 필요한 부분만 옮김.
#   바꾼 것: 모듈을 불러올 때 DLL 을 읽지 않고 load(폴더) 로 읽음(폴더 지정·한글 경로) · 로그 파일을 패키지 폴더에 만들지 않음 ·
#            gguf 파이썬 꾸러미·torch·sounddevice 의존 뺌 · 코덱 복원기는 CPU 실행(DirectML 오류 — 2026-11-17 조사) · 음성 복제(ICL) 길만 남김.
#   저작권 표시는 같은 폴더 LICENSE(MIT). 모델 가중치는 Qwen/Qwen3-TTS-12Hz-0.6B-Base(Apache-2.0)를 변환한 것.
