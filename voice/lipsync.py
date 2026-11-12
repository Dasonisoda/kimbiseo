# 입 모양 시간표(소리만으로) — 음량 + LPC 포먼트 F1·F2 로 아/에/이/오/우를 추정한다.
# Qwen3-TTS 는 음소 시각을 주지 않으므로 이 방식을 쓴다. 결과 형식은 펫과 같음: {dur, fps, lead, frames:[[t, 입모양, 벌림]...]}
# 음소 시각으로 만든 입 모양과 비교한 일치율은 약 70%(입 벌림은 실제 소리 크기를 따르므로 말과 입이 어긋나지는 않음).
import numpy as np

FPS = 100
LEAD = 0.04
ZCENT = {"아": (1.45, 0.05), "에": (0.15, 0.95), "이": (-1.0, 1.25), "오": (0.15, -1.25), "우": (-1.0, -1.0)}


def rms_env(x, sr):
    hop = sr // FPS
    win = int(sr * 0.02)
    n = len(x) // hop
    e = np.zeros(n, np.float32)
    for i in range(n):
        c = i * hop + hop // 2
        seg = x[max(0, c - win // 2):c + win // 2]
        e[i] = np.sqrt((seg ** 2).mean() + 1e-12)
    if n == 0:
        return e
    big = e > e.max() * 0.05
    ref = np.percentile(e[big], 95) if big.any() else (e.max() or 1.0)
    return np.clip(e / ref, 0, 1.3)


def lpc(frame, order):
    r = np.correlate(frame, frame, "full")[len(frame) - 1:len(frame) + order]
    if r[0] <= 0:
        return None
    a = np.zeros(order + 1); a[0] = 1; err = r[0]
    for i in range(1, order + 1):
        acc = r[i] + np.dot(a[1:i], r[i - 1:0:-1])
        k = -acc / err
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        err *= 1 - k * k
        if err <= 0:
            return None
    return a


def formants(x, sr):
    hop = sr // FPS
    win = int(sr * 0.025)
    n = len(x) // hop
    pre = np.append(x[0], x[1:] - 0.94 * x[:-1]) if len(x) else x
    F = np.full((n, 2), np.nan, np.float32)
    w = np.hanning(win)
    for i in range(n):
        c = i * hop + hop // 2
        s = pre[max(0, c - win // 2):max(0, c - win // 2) + win]
        if len(s) < win:
            continue
        a = lpc(s * w, 14)
        if a is None:
            continue
        rts = np.roots(a)
        rts = rts[np.imag(rts) > 0.01]
        fr = np.angle(rts) * sr / (2 * np.pi)
        bw = -np.log(np.abs(rts)) * sr / np.pi
        ok = (fr > 200) & (fr < 3600) & (bw < 450)
        fs = np.sort(fr[ok])
        if len(fs) >= 2:
            F[i] = fs[:2]
    return F


def classify(F, env):
    keys = list(ZCENT)
    C = np.array([ZCENT[k] for k in keys], np.float32)
    voiced = ~np.isnan(F[:, 0]) & (env[:len(F)] >= 0.18)
    if voiced.sum() < 10:
        return [None] * len(F)
    lf = np.log(F[voiced])
    mu, sd = lf.mean(0), lf.std(0) + 1e-6
    lab = []
    for i in range(len(F)):
        if not voiced[i]:
            lab.append(None); continue
        z = (np.log(F[i]) - mu) / sd
        lab.append(keys[int(np.argmin(((C - z) ** 2).sum(1)))])
    return lab


def frames_from_audio(lab, env, dur):
    n = int(np.ceil(dur * FPS))
    fr = []
    for i in range(n + 1):
        j = min(len(env) - 1, i + int(LEAD * FPS))
        win = [l for l in lab[max(0, j - 2):j + 3] if l]
        if j < 0 or env[j] < 0.12 or not win:
            shape, op = "다문", 0.0
        else:
            shape = max(set(win), key=win.count)
            op = min(1.1, 0.25 + 0.85 * float(env[j]) ** 0.7)
        if fr and fr[-1][1] == shape and abs(fr[-1][2] - op) < 0.05:
            continue
        fr.append([round(i / FPS, 3), shape, round(op, 3)])
    return fr


def lip_from_pcm16(pcm16, sr=24000):
    """PCM16(넘파이) → 펫 입 모양 자료. 분석은 16kHz 로 낮춰서(3단계와 같은 조건)."""
    x = pcm16.astype(np.float32) / 32768
    dur = len(x) / sr
    if sr != 16000 and len(x):
        n = int(len(x) * 16000 / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
        sr = 16000
    if len(x) < sr // 10:
        return {"dur": round(dur, 3), "fps": FPS, "lead": LEAD, "frames": [[0.0, "다문", 0.0]]}
    env = rms_env(x, sr)
    lab = classify(formants(x, sr), env)
    return {"dur": round(dur, 3), "fps": FPS, "lead": LEAD, "frames": frames_from_audio(lab, env, dur)}
