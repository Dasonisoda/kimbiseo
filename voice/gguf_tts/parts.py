# 토커(28층)·코드예측기(5층)·프롬프트(음성 복제 ICL)·임베딩 표 — 원본 qwen3_tts_gguf/inference 의
#   assets.py · prompt_builder.py · talker.py · predictor.py · schema/constants.py (MIT, HaujetZhao) 를 옮김. 계산은 원본과 같음.
import os

import numpy as np

from . import lib

PROTOCOL = {"PAD": 2148, "BOS": 2149, "EOS": 2150, "TTS_BOS": 151672, "TTS_EOS": 151673,
            "THINK": 2154, "NOTHINK": 2155, "THINK_BOS": 2156, "THINK_EOS": 2157}
LANGUAGE = {"english": 2050, "german": 2053, "spanish": 2054, "chinese": 2055, "japanese": 2058, "french": 2061,
            "korean": 2064, "russian": 2069, "italian": 2070, "portuguese": 2071}
N_Q = 16


class Assets:
    """글 임베딩(투영된 것)·코덱 임베딩 16개(.npy, 읽기 전용 메모리 매핑)."""

    def __init__(self, model_dir):
        emb = os.path.join(model_dir, "embeddings")
        tt = os.path.join(emb, "text_embedding_projected.npy")
        if not os.path.isfile(tt):
            raise FileNotFoundError(f"목소리 모델 파일 없음: {tt}")
        self.text_table = np.load(tt, mmap_mode="r")
        self.tts_pad = np.asarray(self.text_table[151671], dtype=np.float32)
        pw, pb = os.path.join(emb, "proj_weight.npy"), os.path.join(emb, "proj_bias.npy")
        self.proj = {"weight": np.load(pw, mmap_mode="r"), "bias": np.load(pb, mmap_mode="r")} if os.path.isfile(pw) and os.path.isfile(pb) else None
        self.emb = []
        self.emb_small = []
        for i in range(N_Q):
            p = os.path.join(emb, f"codec_embedding_{i}.npy")
            if not os.path.isfile(p):
                raise FileNotFoundError(f"목소리 모델 파일 없음: {p}")
            t = np.load(p, mmap_mode="r")
            self.emb.append(t)
            self.emb_small.append(t @ self.proj["weight"].T + self.proj["bias"] if self.proj is not None else t)


class PromptBuilder:
    """음성 복제(ICL) 프롬프트: [assistant 머리] + [언어] + [화자 벡터] + [TTS_BOS] + (참고글+글 ⊕ 참고음성 코드) → 남은 글은 걸음마다."""

    def __init__(self, tokenizer, assets):
        self.tok = tokenizer
        self.a = assets

    def ids(self, text):
        r = self.tok.encode(text)
        return r.ids if hasattr(r, "ids") else r

    def clone(self, text, ref_text, ref_codes, spk_emb, lang_id):
        a, p = self.a, PROTOCOL
        tts_pad = a.tts_pad
        dim = tts_pad.shape[0]
        text_ids = self.ids(ref_text + text)
        prefix = [a.text_table[t] for t in self.ids("<|im_start|>assistant\n")]
        pre = [p["THINK"], p["THINK_BOS"], lang_id, p["THINK_EOS"]] if lang_id is not None else [p["NOTHINK"], p["THINK_BOS"], p["THINK_EOS"]]
        prefix += [tts_pad + a.emb[0][t] for t in pre]
        if spk_emb is not None:
            prefix.append(tts_pad + spk_emb)
        prefix.append(a.text_table[p["TTS_BOS"]] + a.emb[0][p["PAD"]])
        text_pool = a.text_table[text_ids + [p["TTS_EOS"]]]
        audio = [a.emb[0][p["BOS"]]]
        for t in range(ref_codes.shape[0]):
            s = np.zeros(dim, dtype=np.float32)
            for q in range(N_Q):
                s += a.emb[q][ref_codes[t, q]]
            audio.append(s)
        audio = np.array(audio)
        tl, al = len(text_pool), len(audio)
        if tl > al:
            body, trailing = text_pool[:al] + audio, text_pool[al:]
        else:
            body, trailing = np.vstack([text_pool, np.tile(tts_pad, (al - tl, 1))]) + audio, None
        x = np.vstack([np.array(prefix), body]).astype(np.float32)
        tr = trailing.astype(np.float32) if trailing is not None and len(trailing) else None
        return x, tr


class Talker:
    def __init__(self, model, ctx, batch, assets):
        self.model, self.ctx, self.batch, self.a = model, ctx, batch, assets
        self.pos = 0
        self.trailing = None
        self.step = 0
        self._p1 = np.zeros(4, dtype=np.int32)
        self.n_ctx = 2048

    def clear(self):
        self.ctx.clear()
        self.pos = 0
        self.trailing = None
        self.step = 0

    def prefill(self, x, trailing):
        n = x.shape[0]
        self.trailing, self.step = trailing, 0
        base = np.arange(self.pos, self.pos + n, dtype=np.int32)
        pos = np.concatenate([base, base, base, np.zeros(n, dtype=np.int32)])    # Qwen3 위치 평면 3개 + 0
        self.batch.set_embd(x, pos=pos)
        st = self.ctx.decode(self.batch)
        if st != 0:
            raise RuntimeError(f"토커 프롬프트 처리 실패({st}) — 글이 너무 길거나 장치 메모리 모자람")
        dim = self.a.text_table.shape[1]
        h = np.ctypeslib.as_array(self.ctx.embeddings(), shape=(n, dim))[-1].copy()
        self.pos += n
        return h

    def step_audio(self, audio_sum):
        if self.pos >= self.n_ctx - 1:
            raise RuntimeError("토커 문맥 넘침")
        tv = self.trailing[self.step] if (self.trailing is not None and self.step < len(self.trailing)) else self.a.tts_pad
        x = (audio_sum + tv).reshape(1, -1)
        self.step += 1
        self._p1[0:3] = self.pos
        self.batch.set_embd(x, pos=self._p1)
        if self.ctx.decode(self.batch) != 0:
            raise RuntimeError(f"토커 한 걸음 실패(자리 {self.pos})")
        dim = self.a.text_table.shape[1]
        h = np.ctypeslib.as_array(self.ctx.embeddings(), shape=(1, dim))[0].copy()
        self.pos += 1
        return h


class Predictor:
    """한 프레임의 나머지 코드 15개(Q1~Q15)를 차례로 뽑음."""

    def __init__(self, model, ctx, batch, assets):
        self.model, self.ctx, self.batch, self.a = model, ctx, batch, assets

    def frame(self, h, code0, sampler):
        a = self.a
        hs = h @ a.proj["weight"].T + a.proj["bias"] if a.proj is not None else h
        codes = [int(code0)]
        embs = [np.asarray(a.emb[0][code0], dtype=np.float32)]
        self.ctx.clear()
        self.batch.set_embd(np.stack([hs, a.emb_small[0][code0]], axis=0), pos=0)
        self.ctx.decode(self.batch)
        for cs in range(1, N_Q):
            s0 = (cs - 1) * 2048
            c = int(sampler.sample(self.ctx, limit=(s0, s0 + 2048))) - s0
            codes.append(c)
            embs.append(np.asarray(a.emb[cs][c], dtype=np.float32))
            if cs < N_Q - 1:
                self.batch.set_embd(np.asarray(a.emb_small[cs][c], dtype=np.float32).reshape(1, -1), pos=cs + 1)
                self.ctx.decode(self.batch)
        return codes, embs


def make_talker(model, assets, threads=None, n_ctx=2048):
    t = Talker(model, lib.Context(model, n_ctx=n_ctx, embeddings=True, threads=threads), lib.Batch(n_ctx, model.n_embd), assets)
    t.n_ctx = n_ctx
    return t


def make_predictor(model, assets, threads=None):
    return Predictor(model, lib.Context(model, n_ctx=64, embeddings=False, threads=threads), lib.Batch(2, model.n_embd), assets)
