# 코덱 복원기(상태 있는 ONNX, 조각 스트리밍)·코덱 인코더·화자 인코더·멜 — 원본 qwen3_tts_gguf/inference 의
#   decoder.py(StatefulDecoder) · encoder.py · utils/mel.py · utils/audio.py(MIT, HaujetZhao) 를 옮김.
#   바꾼 것: 실행 장치는 CPU 만(DirectML 은 Reshape 노드 오류 — 2026-11-17 조사, onnxruntime 기본 꾸러미에도 없음) ·
#            OMP_NUM_THREADS 를 프로세스 전체에 박지 않고 세션 스레드 수로 · ONNX 파일 경로는 한글이어도 됨(onnxruntime 넓은 문자 경로).
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

SR = 24000
SPF = 1920


@dataclass
class DecoderState:
    pre_conv_history: Optional[np.ndarray] = None
    latent_buffer: Optional[np.ndarray] = None
    conv_history: Optional[np.ndarray] = None
    kv_cache: List[np.ndarray] = field(default_factory=list)
    skip_samples: int = 0
    latent_audio: Optional[np.ndarray] = None


def _session(path, threads):
    import onnxruntime as ort
    if not os.path.isfile(path):
        raise FileNotFoundError(f"목소리 모델 파일 없음: {path}")
    so = ort.SessionOptions()
    so.log_severity_level = 3
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if threads:
        so.intra_op_num_threads = int(threads)
    return ort.InferenceSession(path, sess_options=so, providers=["CPUExecutionProvider"])


class StatefulDecoder:
    NUM_LAYERS, NUM_HEADS, HEAD_DIM = 8, 16, 64

    def __init__(self, onnx_path, chunk_size=12, threads=None):
        self.chunk_size = chunk_size
        self.sess = _session(onnx_path, threads)
        fi = next(i for i in self.sess.get_inputs() if "float" in i.type)
        self.dtype = np.float16 if "float16" in fi.type else np.float32
        self.out_names = [o.name for o in self.sess.get_outputs()]
        self.decode(np.zeros((self.chunk_size, 16), dtype=np.int64), state=self.create_state(72), is_final=True)   # 예열

    def create_state(self, history=0):
        d = self.dtype
        if history:
            pre, lat, conv = np.zeros((1, 512, 2), d), np.zeros((1, 1024, 4), d), np.zeros((1, 1024, 4), d)
        else:
            pre, lat, conv = np.zeros((1, 512, 0), d), np.zeros((1, 1024, 0), d), np.zeros((1, 1024, 0), d)
        kv = []
        for _ in range(self.NUM_LAYERS):
            kv.append(np.zeros((1, self.NUM_HEADS, max(0, history), self.HEAD_DIM), d))
            kv.append(np.zeros((1, self.NUM_HEADS, max(0, history), self.HEAD_DIM), d))
        return DecoderState(pre, lat, conv, kv, 0, None)

    def decode(self, codes, state=None, is_final=False):
        """codes [N,16] → (소리 float32, 새 상태). chunk_size 보다 길면 나눠서."""
        codes = np.asarray(codes, dtype=np.int64)
        if codes.ndim == 1:
            codes = codes.reshape(-1, 16)
        n = codes.shape[0]
        if n <= self.chunk_size:
            return self._decode(codes, state, is_final)
        out, st = [], state
        for i in range(0, n, self.chunk_size):
            last = i + self.chunk_size >= n
            a, st = self._decode(codes[i:i + self.chunk_size], st, is_final if last else False)
            out.append(a)
        return np.concatenate(out), st

    def _decode(self, codes, state, is_final):
        if state is None:
            state = self.create_state()
        skip = state.skip_samples
        codes = codes[np.newaxis, ...]
        if codes.shape[1] == 0:
            if is_final and state.latent_audio is not None:
                a = state.latent_audio
                return a.astype(np.float32), DecoderState(state.pre_conv_history, state.latent_buffer, state.conv_history,
                                                          state.kv_cache, 4 * SPF, None)
            return np.zeros(0, np.float32), state
        feed = {"audio_codes": codes, "is_last": np.array([1.0 if is_final else 0.0], dtype=self.dtype),
                "pre_conv_history": state.pre_conv_history, "latent_buffer": state.latent_buffer, "conv_history": state.conv_history}
        for i in range(self.NUM_LAYERS):
            feed[f"past_key_{i}"] = state.kv_cache[2 * i]
            feed[f"past_value_{i}"] = state.kv_cache[2 * i + 1]
        o = self.sess.run(self.out_names, feed)
        wav, valid = o[0], int(o[1][0])
        kv = []
        for i in range(self.NUM_LAYERS):
            kv.append(o[5 + i])
            kv.append(o[5 + self.NUM_LAYERS + i])
        new = DecoderState(o[2], o[3], o[4], kv, 0, None)
        if is_final:
            audio = wav[0]
        else:
            audio = wav[0, :valid] if valid > 0 else np.zeros(0, np.float32)
            new.latent_audio = wav[0, valid:]
        if skip > 0 and len(audio) > 0:
            if len(audio) <= skip:
                skip -= len(audio)
                audio = np.zeros(0, np.float32)
            else:
                audio, skip = audio[skip:], 0
        new.skip_samples = 4 * SPF if is_final else skip
        return audio.astype(np.float32), new


class CodecEncoder:
    def __init__(self, onnx_path, threads=None):
        self.sess = _session(onnx_path, threads)
        self.dtype = np.float16 if "float16" in self.sess.get_inputs()[0].type else np.float32

    def encode(self, wav):
        return self.sess.run(["audio_codes"], {"input_values": wav.reshape(1, -1).astype(self.dtype)})[0][0]


class MelExtractor:
    def __init__(self, sr=24000, n_fft=1024, hop_length=256, n_mels=128, fmin=0.0, fmax=12000.0):
        from scipy.signal.windows import hann
        self.sr, self.n_fft, self.hop, self.n_mels, self.fmin, self.fmax = sr, n_fft, hop_length, n_mels, fmin, fmax
        self.basis = self._basis()
        self.window = hann(n_fft, sym=False).astype(np.float32)

    @staticmethod
    def _hz_to_mel(f):
        f = np.asanyarray(f, dtype=np.float64)
        sp, lo = 200.0 / 3, 1000.0
        lo_mel, step = lo / sp, np.log(6.4) / 27.0
        m = f / sp
        if m.ndim > 0:
            k = f >= lo
            m[k] = lo_mel + np.log(f[k] / lo) / step
        elif f >= lo:
            m = lo_mel + np.log(f / lo) / step
        return m

    @staticmethod
    def _mel_to_hz(m):
        m = np.asanyarray(m, dtype=np.float64)
        sp, lo = 200.0 / 3, 1000.0
        lo_mel, step = lo / sp, np.log(6.4) / 27.0
        f = sp * m
        if m.ndim > 0:
            k = m >= lo_mel
            f[k] = lo * np.exp(step * (m[k] - lo_mel))
        elif m >= lo_mel:
            f = lo * np.exp(step * (m - lo_mel))
        return f

    def _basis(self):
        fft_f = np.linspace(0, self.sr / 2, int(1 + self.n_fft // 2))
        mf = self._mel_to_hz(np.linspace(self._hz_to_mel(self.fmin), self._hz_to_mel(self.fmax), self.n_mels + 2))
        b = np.zeros((self.n_mels, len(fft_f)))
        for i in range(self.n_mels):
            lo, c, hi = mf[i], mf[i + 1], mf[i + 2]
            b[i] = np.maximum(0, np.minimum((fft_f - lo) / (c - lo), (hi - fft_f) / (hi - c)))
        b *= (2.0 / (mf[2:self.n_mels + 2] - mf[:self.n_mels]))[:, np.newaxis]
        return b.astype(np.float32)

    def extract(self, wav):
        from scipy.fft import rfft
        pad = (self.n_fft - self.hop) // 2
        w = np.pad(wav, (pad, pad), mode="reflect")
        n = 1 + (len(w) - self.n_fft) // self.hop
        fr = np.lib.stride_tricks.as_strided(w, shape=(n, self.n_fft), strides=(w.strides[0] * self.hop, w.strides[0]))
        mag = np.sqrt(np.abs(rfft(fr * self.window, n=self.n_fft, axis=1)) ** 2 + 1e-9).T
        return np.log(np.maximum(np.dot(self.basis, mag), 1e-5)).T


class SpeakerEncoder:
    def __init__(self, onnx_path, threads=None):
        self.sess = _session(onnx_path, threads)
        self.dtype = np.float16 if "float16" in self.sess.get_inputs()[0].type else np.float32
        self.mel = MelExtractor()

    def encode(self, wav):
        m = self.mel.extract(wav)[np.newaxis, ...].astype(self.dtype)
        return np.asarray(self.sess.run(["spk_emb"], {"mels": m})[0][0], dtype=np.float32)


def _resample(x, up, down, window_size=10):
    g = math.gcd(up, down)
    up, down = up // g, down // g
    if up == down:
        return x.copy()
    mr = max(up, down)
    half = window_size * mr
    nt = 2 * half + 1
    t = np.arange(nt) - half
    h = np.sinc(t / mr) * (np.i0(5.0 * np.sqrt(1 - (2 * t / (nt - 1)) ** 2)) / np.i0(5.0))
    h = h * (up / np.sum(h))
    n_out = int(math.ceil(len(x) * up / down))
    xu = np.zeros(len(x) * up + nt, dtype=np.float32)
    xu[:len(x) * up:up] = x
    y = np.convolve(xu, h, mode="full")
    off = (nt - 1) // 2
    return y[off:off + len(x) * up:down][:n_out].astype(np.float32)


def load_wav(path, sr=SR):
    import soundfile as sf
    a, s = sf.read(path, dtype="float32")
    if a.ndim > 1:
        a = a.mean(axis=1)
    if s != sr:
        a = _resample(a, sr, s)
    return a.astype(np.float32)
