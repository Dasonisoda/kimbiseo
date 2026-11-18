# 통역 원어민 목소리 프로그램 — 귀 서버(ear_server.py)가 자식 프로세스로 켜고, 표준 입출력으로만 주고받는다(따로 도는 프로그램).
#   실행 환경: 설치 폴더 runtime\python-interp (선택 부품 — 설정 화면 '통역 목소리 받기', installer/locks/interp.json). 그래픽카드 안 씀.
#   엔진
#     kokoro:<언어글자>:<목소리>  Kokoro-82M(hexgrad, Apache-2.0) — a 영어 · j 일본어 · z 중국어 · e 스페인어 · f 프랑스어 · i 이탈리아어
#                                 모델 = <모델 폴더>\kokoro-82m (config.json · kokoro-v1_0.pth · voices\<목소리>.pt)
#     piper:<목소리 이름>          Piper(piper-tts, GPL-3.0 — 사용자 PC 가 PyPI 에서 직접 받은 꾸러미를 이 프로그램이 불러 씀)
#                                 모델 = <모델 폴더>\piper-<목소리 이름>\<목소리 이름>.onnx(+ .onnx.json)
#     thai:<목소리 묶음>            태국어(0.1.17~) — MrJMThaiTTS(Kokoro 태국어 판 ONNX, onnxruntime · torch 안 씀)
#                                 모델 = <모델 폴더>	hai-mrjm(kokoro_thai.fp16w.onnx · <묶음>.npy · config.json)
#                                 글자 → 발음 = <모델 폴더>astthaig2p(awslabs/FastThaiG2P 고정 커밋 파일 — 꾸러미 pythainlp 를 씀)
#   규약: 요청 한 줄 {"voice":"kokoro:a:af_heart","text":"..."} → 머리 한 줄 {"n":바이트,"sr":표본율} 또는 {"error":"..."} + int16 모노 PCM
#         켠 뒤 준비되면 {"ready": true} 한 줄(귀 서버는 이 줄을 받은 뒤 요청을 보냄 — 처음 불러오기 10~30초)
#   espeak-ng(Kokoro 의 영어·유럽 말 읽기, Piper 안의 읽기)는 한글 등 영문 아닌 경로를 못 읽음 → 자료 폴더를 %LOCALAPPDATA%\KimBiseo\espeak(영문 경로)로
#   한 번 복사해 씀(사용자 이름이 한글이라 그 경로도 영문이 아니면 %PUBLIC% 아래로).
#   실행: <python-interp>\python.exe interp_voice.py --models <모델 폴더> [--threads 4]
import argparse
import json
import os
import shutil
import sys
import time

OUT = os.fdopen(os.dup(1), "wb")  # 진짜 표준 출력은 소리 전용 — 라이브러리가 찍는 글은 전부 표준 오류로
os.dup2(2, 1)
sys.stdout = sys.stderr
KOKORO_LANGS = "abefhijpz"


def log(*a):
    print(time.strftime("%H:%M:%S"), "[통역 목소리]", *a, file=sys.stderr, flush=True)


def ascii_dir(name):
    """espeak 자료를 둘 영문 경로(없으면 None)."""
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("PUBLIC"), os.environ.get("ProgramData")):
        if base:
            d = os.path.join(base, "KimBiseo", "espeak", name)
            if d.isascii():
                return d
    return None


def copy_once(src, name):
    dst = ascii_dir(name)
    if not dst or not os.path.isdir(src):
        return src
    if src.isascii():
        return src
    mark = os.path.join(dst, ".copied")
    if not os.path.isfile(mark):
        shutil.copytree(src, dst, dirs_exist_ok=True)
        open(mark, "w").close()
    return dst


class Kokoro:
    def __init__(self, root, threads):
        try:
            import espeakng_loader
            data = copy_once(espeakng_loader.get_data_path(), "kokoro")
            espeakng_loader.get_data_path = lambda: data
        except ImportError:
            pass
        import torch
        from kokoro import KModel
        torch.set_num_threads(threads)
        self.root = root
        self.model = KModel(config=os.path.join(root, "config.json"), model=os.path.join(root, "kokoro-v1_0.pth"),
                            repo_id="hexgrad/Kokoro-82M").eval()
        self.pipes = {}
        self.voices = {}

    def say(self, lang, voice, text):
        import numpy as np
        import torch
        from kokoro import KPipeline
        if len(lang) != 1 or lang not in KOKORO_LANGS:
            raise ValueError(f"모르는 언어 {lang}")
        p = self.pipes.get(lang)
        if p is None:
            p = self.pipes[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", model=self.model)
        vf = os.path.join(self.root, "voices", os.path.basename(voice) + ".pt")
        if not os.path.isfile(vf):
            raise FileNotFoundError(f"목소리 파일 없음: {os.path.basename(vf)}")
        pack = self.voices.get(vf)
        if pack is None:
            pack = self.voices[vf] = torch.load(vf, weights_only=True)
        with torch.inference_mode():
            parts = [r.audio.numpy() for r in p(text, voice=pack) if r.audio is not None]
        a = np.concatenate(parts) if parts else np.zeros(0, np.float32)
        return (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes(), 24000


class Thai:
    """태국어 — FastThaiG2P 의 TTS(ONNX 판)를 그대로 씀. 긴 글은 띄어쓰기에서 잘라 차례로 만들고 사이에 짧은 쉼."""
    CHUNK = 120   # 글자 수(태국어는 문장 사이를 띄어 씀). 발음 510개를 넘으면 더 잘게
    SR = 24000

    def __init__(self, models, threads):
        g2p = os.path.join(models, "fastthaig2p")
        if not os.path.isfile(os.path.join(g2p, "fastthaig2p", "tts.py")):
            raise FileNotFoundError("태국어 글자 읽기(fastthaig2p)가 없음 — 설정 → 통역 → '통역 목소리 받기'")
        # pythainlp 가 처음 불릴 때 만드는 자료 폴더를 사용자 홈 대신 모델 폴더 옆(_pythainlp)에
        os.environ.setdefault("PYTHAINLP_DATA_DIR", os.path.join(models, "_pythainlp"))
        if g2p not in sys.path:
            sys.path.insert(0, g2p)
        self.root = os.path.join(models, "thai-mrjm")
        self.threads = threads
        self.tts = {}

    def _engine(self, name):
        t = self.tts.get(name)
        if t is None:
            from fastthaig2p.tts import TTS
            vp = os.path.join(self.root, os.path.basename(name) + ".npy")
            if not os.path.isfile(vp):
                raise FileNotFoundError("목소리 파일 없음: thai-mrjm/" + os.path.basename(vp))
            t = self.tts[name] = TTS(os.path.join(self.root, "kokoro_thai.fp16w.onnx"), vp,
                                     config_path=os.path.join(self.root, "config.json"), intra_op_threads=self.threads)
        return t

    @classmethod
    def chunks(cls, text, size=None):
        """띄어쓰기에서 잘라 size 글자 안쪽으로(띄어쓰기가 없으면 그대로 자름)."""
        size = size or cls.CHUNK
        out, cur = [], ""
        for w in str(text or "").split():
            while len(w) > size:
                if cur:
                    out.append(cur)
                    cur = ""
                out.append(w[:size])
                w = w[size:]
            if cur and len(cur) + 1 + len(w) > size:
                out.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            out.append(cur)
        return out

    def say(self, name, text):
        import numpy as np
        t = self._engine(name)
        parts, gap = [], np.zeros(int(self.SR * 0.18), np.float32)
        todo = self.chunks(text)
        while todo:
            c = todo.pop(0)
            try:
                a = np.asarray(t.generate(c), np.float32).ravel()
            except ValueError:   # 발음이 510개를 넘음 → 반으로
                if len(c) < 8:
                    raise
                todo[:0] = self.chunks(c, max(8, len(c) // 2))
                continue
            if a.size:
                parts += [a, gap]
        a = np.concatenate(parts[:-1]) if parts else np.zeros(0, np.float32)
        return (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes(), self.SR


class Piper:
    def __init__(self, root):
        import piper
        self.root = root
        self.voices = {}
        pkg = os.path.dirname(piper.__file__)
        self.espeak = copy_once(os.path.join(pkg, "espeak-ng-data"), "piper")

    def say(self, name, text):
        from piper import PiperVoice
        name = os.path.basename(name)
        v = self.voices.get(name)
        if v is None:
            f = os.path.join(self.root, "piper-" + name, name + ".onnx")
            if not os.path.isfile(f):
                raise FileNotFoundError(f"목소리 파일 없음: piper-{name}")
            try:
                v = PiperVoice.load(f, espeak_data_dir=self.espeak)
            except TypeError:
                v = PiperVoice.load(f)
            self.voices[name] = v
        pcm, sr = bytearray(), int(v.config.sample_rate)
        for ch in v.synthesize(text):
            pcm += ch.audio_int16_bytes
            sr = int(getattr(ch, "sample_rate", sr) or sr)
        return bytes(pcm), sr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--warm", default="", help="미리 불러올 목소리(쉼표로)")
    a = ap.parse_args()
    eng = {}

    def engine(kind):
        if kind not in eng:
            t0 = time.perf_counter()
            if kind == "kokoro":
                eng[kind] = Kokoro(os.path.join(a.models, "kokoro-82m"), a.threads)
            elif kind == "thai":
                eng[kind] = Thai(a.models, a.threads)
            else:
                eng[kind] = Piper(a.models)
            log(f"{kind} 불러옴 {time.perf_counter() - t0:.1f}초")
        return eng[kind]

    def say(voice, text):
        kind, _, rest = voice.partition(":")
        if kind == "kokoro":
            lang, _, name = rest.partition(":")
            return engine("kokoro").say(lang, name, text)
        if kind == "piper":
            return engine("piper").say(rest, text)
        if kind == "thai":
            return engine("thai").say(rest, text)
        raise ValueError(f"모르는 목소리 {voice}")

    for v in [x for x in a.warm.split(",") if x]:
        try:
            say(v, "ok")
        except Exception as ex:  # noqa: BLE001
            log("미리 불러오기 실패", v, repr(ex))
    log("준비")
    OUT.write(b'{"ready": true}\n')
    OUT.flush()
    for line in sys.stdin.buffer:
        try:
            req = json.loads(line.decode("utf-8"))
            voice, text = str(req.get("voice") or ""), str(req.get("text") or "")[:600]
            t0 = time.perf_counter()
            pcm, sr = say(voice, text)
            OUT.write((json.dumps({"n": len(pcm), "sr": sr}) + "\n").encode("utf-8") + pcm)
            log(f"{voice} 글 {len(text)}자 → 소리 {len(pcm) / 2 / sr:.1f}초, {time.perf_counter() - t0:.2f}초")
        except Exception as ex:  # noqa: BLE001
            OUT.write((json.dumps({"error": f"{type(ex).__name__}: {ex}"[:200]}, ensure_ascii=False) + "\n").encode("utf-8"))
            log("오류", repr(ex))
        OUT.flush()


if __name__ == "__main__":
    main()
