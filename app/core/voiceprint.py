# 내 목소리 등록·확인(선택 기능, 기본 꺼짐) — '등록한 목소리만 명령 받기'.
#   모델: NVIDIA NeMo TitaNet-small(sherpa-onnx 가 onnx 로 바꾼 판, NeMo 툴킷 조건 = Apache-2.0) — installer/models.json 'titanet-small'.
#   본체 환경에 이미 있는 onnxruntime + numpy 로만 돈다(새 꾸러미 없음). 입력 특징(80 멜 로그 필터뱅크, 25ms/10ms, hann)은
#   sherpa-onnx(kaldi-native-fbank) 와 같게 맞췄다 — 검증결과\23단계_폰앱_목소리등록\특징_맞추기 결과(같은 소리 코사인 0.99+).
#   등록: 문장 몇 개를 읽은 소리 → 임베딩 평균(192개 숫자) → 자료 폴더 voiceprint\me.json. 소리 자체는 저장하지 않는다.
#   확인: 말 한 조각 → 임베딩 → 등록 평균과 코사인. '목소리등록.문턱'(기본 0.45) 이상이면 등록한 사람.
#   1초보다 짧은 말은 점수가 흔들려 '짧음'으로 따로 돌려준다(본체가 짧은 말은 문턱을 조금 낮춰 봄).
import json
import os
import threading
import time

import numpy as np

SR = 16000
WIN, HOP, NFFT, NMEL = 400, 160, 512, 80
MIN_SEC = 0.6           # 이보다 짧으면 점수를 내지 않음
SHORT_SEC = 1.2         # 이보다 짧으면 '짧음'
ENROLL_MIN = 3          # 등록에 필요한 문장 수
ENROLL_MIN_SEC = 1.5    # 등록 문장 하나의 최소 말 길이
FMAX = 7600.0          # kaldi 기본 high_freq = -400 → 8000-400
SENTENCES = ("오늘 날씨가 맑아서 산책하기 좋은 날이에요.",          # 등록 때 읽을 문장(3~4초짜리, 받침·모음 고루)
             "내일 아침 일곱 시에 알람을 맞춰 주세요.",
             "냉장고에 우유랑 달걀이 얼마나 남았는지 궁금해요.",
             "주말에는 가족과 함께 바닷가에 다녀올 거예요.",
             "새로 나온 노트북 가격을 검색해서 알려 주세요.")
MODEL_NAME = "titanet-small"
MODEL_FILE = "nemo_en_titanet_small.onnx"

_MEL = {}


def _hz_to_mel_slaney(f):
    f = np.asarray(f, np.float64)
    f_sp = 200.0 / 3
    mel = f / f_sp
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mel)


def _mel_to_hz_slaney(m):
    m = np.asarray(m, np.float64)
    f_sp = 200.0 / 3
    f = f_sp * m
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), f)


def mel_bank(n_mels=NMEL, n_fft=NFFT, sr=SR, fmin=0.0, fmax=None):
    """librosa.filters.mel(htk=False, norm='slaney') 와 같은 삼각 필터(kaldi-native-fbank 의 is_librosa 모드)."""
    key = (n_mels, n_fft, sr, fmin, fmax)
    if key in _MEL:
        return _MEL[key]
    fmax = sr / 2 if fmax is None else fmax
    fft_f = np.linspace(0, sr / 2, n_fft // 2 + 1)
    mel_f = _mel_to_hz_slaney(np.linspace(_hz_to_mel_slaney(fmin), _hz_to_mel_slaney(fmax), n_mels + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fft_f[None, :]
    w = np.zeros((n_mels, len(fft_f)))
    for i in range(n_mels):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        w[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels])
    w *= enorm[:, None]
    _MEL[key] = w.astype(np.float32)
    return _MEL[key]


def features(wave):
    """float32 [-1,1] 16kHz 모노 → (프레임 수, 80) 로그 멜(프레임별 정규화 전)."""
    x = np.asarray(wave, np.float32)
    if len(x) < WIN:
        return np.zeros((0, NMEL), np.float32)
    n = 1 + (len(x) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    fr = x[idx].astype(np.float64)
    pre = fr.copy()
    pre[:, 1:] -= 0.97 * fr[:, :-1]
    pre[:, 0] -= 0.97 * fr[:, 0]
    win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(WIN) / (WIN - 1))
    spec = np.abs(np.fft.rfft(pre * win, NFFT)) ** 2
    mel = spec @ mel_bank(fmax=FMAX).T.astype(np.float64)
    return np.log(np.maximum(mel, np.finfo(np.float32).eps)).astype(np.float32)


def normalize(feat):
    m = feat.mean(0, keepdims=True)
    c = feat - m
    sd = np.sqrt((c * c).sum(0, keepdims=True) / max(1, len(feat) - 1))
    return (c / (sd + 1e-5)).astype(np.float32)


def embed_with(sess, wave):
    f = features(wave)
    if len(f) < 2:
        return None
    f = normalize(f)
    pad = (-len(f)) % 16
    if pad:
        f = np.concatenate([f, np.zeros((pad, NMEL), np.float32)])
    x = f.T[None, :, :]
    out = sess.run(["embs"], {"audio_signal": x, "length": np.array([len(f)], np.int64)})[0]
    return np.asarray(out[0], np.float32)


def cosine(a, b):
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / d) if d > 0 else 0.0


def speech_part(wave, frame=320):
    """앞뒤 조용한 부분을 잘라 말소리만(등록·확인 모두). 소리 크기 상위 90% 의 15% 를 문턱으로."""
    x = np.asarray(wave, np.float32)
    if len(x) < frame * 3:
        return x
    n = len(x) // frame
    e = np.sqrt((x[:n * frame].reshape(n, frame) ** 2).mean(1))
    th = max(0.003, float(np.percentile(e, 90)) * 0.15)
    on = np.where(e >= th)[0]
    if not len(on):
        return x[:0]
    a, b = max(0, on[0] - 3), min(n, on[-1] + 4)
    return x[a * frame:b * frame]


class VoicePrint:
    """등록·확인. 모델은 처음 쓸 때 불러옴(본체 시작을 늦추지 않게)."""

    def __init__(self, cfg, log=print):
        self.cfg = cfg
        self.log = log
        self.lock = threading.Lock()
        self.sess = None
        self.error = ""
        self.me = None
        self._load_me()

    # ---- 파일
    def folder(self):
        from . import config as C
        return os.path.join(C.path(self.cfg, "자료"), "voiceprint")

    def me_path(self):
        return os.path.join(self.folder(), "me.json")

    def model_path(self):
        from . import config as C
        return os.path.join(C.path(self.cfg, "모델"), MODEL_NAME, MODEL_FILE)     # 설치 프로그램이 받는 곳(get_models.ensure_model)

    def _load_me(self):
        try:
            with open(self.me_path(), encoding="utf-8") as f:
                d = json.load(f)
            emb = np.asarray(d.get("emb") or [], np.float32)
            self.me = {"emb": emb, "n": int(d.get("n") or 0), "등록": d.get("등록") or "", "점수": d.get("점수") or []} \
                if emb.shape == (192,) else None
        except (OSError, ValueError, TypeError):
            self.me = None

    # ---- 설정
    def conf(self):
        return dict((self.cfg.get("목소리등록") or {}))

    def gate_on(self):
        """'등록한 목소리만 명령 받기' 가 켜져 있고 등록·확인 모델이 다 있어야 문이 닫힌다
        (등록이 없거나 모델 파일이 지워졌으면 막지 않고 설정 화면에 알림 — 말로 아무것도 못 하게 잠기지 않게)."""
        return bool(self.conf().get("명령만")) and self.me is not None and self.ready()

    def threshold(self, short=False):
        c = self.conf()
        th = float(c.get("문턱", 0.40))
        return th - float(c.get("짧은말_낮춤", 0.08)) if short else th

    # ---- 모델
    def ready(self):
        return os.path.isfile(self.model_path())

    def _session(self):
        with self.lock:
            if self.sess is None:
                p = self.model_path()
                if not os.path.isfile(p):
                    self.error = "목소리 확인 모델이 없어요(설정 → 내 목소리 → '확인 모델 받기')"
                    raise FileNotFoundError(self.error)
                import onnxruntime as ort
                so = ort.SessionOptions()
                so.intra_op_num_threads = 1
                so.inter_op_num_threads = 1
                with open(p, "rb") as f:        # 한글 경로도 되게 바이트로 넘김
                    self.sess = ort.InferenceSession(f.read(), sess_options=so, providers=["CPUExecutionProvider"])
            return self.sess

    def embed(self, wave):
        w = speech_part(wave)
        if len(w) < MIN_SEC * SR:
            return None, len(w) / SR
        return embed_with(self._session(), w), len(w) / SR

    # ---- 확인
    def score_pcm(self, pcm16):
        """int16 PCM 바이트 → {"점수", "등록됨", "짧음", "초", "ms"} (등록 없음·짧음이면 점수 None)."""
        t0 = time.perf_counter()
        x = np.frombuffer(pcm16, np.int16).astype(np.float32) / 32768.0
        if self.me is None:
            return {"점수": None, "등록됨": False, "짧음": False, "초": len(x) / SR, "ms": 0}
        try:
            e, sec = self.embed(x)
        except Exception as ex:  # noqa: BLE001
            self.error = str(ex)[:200]
            return {"점수": None, "등록됨": True, "짧음": False, "초": len(x) / SR, "ms": 0, "오류": self.error}
        if e is None:
            return {"점수": None, "등록됨": True, "짧음": True, "초": sec, "ms": round((time.perf_counter() - t0) * 1000)}
        return {"점수": round(cosine(e, self.me["emb"]), 3), "등록됨": True, "짧음": sec < SHORT_SEC, "초": round(sec, 2),
                "ms": round((time.perf_counter() - t0) * 1000)}

    def is_me(self, r):
        """score_pcm 결과 → True(등록한 사람)/False. 점수를 못 내면(너무 짧음) 막는다(명령만 켠 사람은 안전 쪽)."""
        if not r or r.get("점수") is None:
            return False
        return r["점수"] >= self.threshold(short=bool(r.get("짧음")))

    # ---- 등록
    def enroll(self, clips):
        """clips = [int16 PCM 바이트 …] (문장 하나씩). → (ok, 안내, 정보). 저장하는 것은 임베딩 평균뿐."""
        embs, secs = [], []
        for c in clips:
            x = np.frombuffer(c, np.int16).astype(np.float32) / 32768.0
            e, sec = self.embed(x)
            if e is None or sec < ENROLL_MIN_SEC:
                continue
            embs.append(e / max(1e-9, float(np.linalg.norm(e))))
            secs.append(sec)
        if len(embs) < ENROLL_MIN:
            return False, f"또렷한 문장이 {len(embs)}개뿐이에요. 문장을 {ENROLL_MIN}개 이상 또박또박 읽어 주세요.", {}
        mean = np.mean(embs, 0)
        self_sc = [round(cosine(e, mean), 3) for e in embs]
        # 섞인 목소리(두 사람이 번갈아 읽음 등)는 평균과 덜 닮은 문장이 나옴 → 등록 거절
        if min(self_sc) < 0.55:
            return False, "읽은 문장끼리 목소리가 달라요. 조용한 곳에서 한 사람이 다시 읽어 주세요.", {"점수": self_sc}
        os.makedirs(self.folder(), exist_ok=True)
        rec = {"emb": [round(float(v), 6) for v in mean], "n": len(embs), "등록": time.strftime("%Y-%m-%d %H:%M"),
               "점수": self_sc, "모델": MODEL_NAME, "말_초": round(float(sum(secs)), 1)}
        tmp = self.me_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, self.me_path())
        self._load_me()
        return True, f"목소리를 등록했어요(문장 {len(embs)}개).", {"점수": self_sc}

    def forget(self):
        try:
            os.remove(self.me_path())
        except OSError:
            pass
        self.me = None

    def view(self):
        c = self.conf()
        return {"등록됨": self.me is not None, "등록": (self.me or {}).get("등록", ""), "문장": (self.me or {}).get("n", 0),
                "명령만": bool(c.get("명령만")), "모델있음": self.ready(), "문턱": self.threshold(), "오류": self.error,
                "작동중": self.gate_on()}
