# llama.cpp(b10621) ctypes 묶음 — 원본 qwen3_tts_gguf/inference/llama.py(MIT, HaujetZhao)에서 TTS 에 쓰는 부분만.
#   구조체 배치는 llama.cpp b10621 기준 → DLL 도 그 판(installer/radeon/runtimes.json 'llama_cpp_tts')만 쓴다. 다른 판 DLL 을 넣으면 load() 가 판을 확인하고 멈춤.
#   load(폴더): 그 폴더의 ggml/llama DLL 을 읽고 백엔드(불칸·CPU)를 그 폴더에서 찾는다(파이썬 실행 폴더가 아니라).
#   한글 경로: 모델 경로는 UTF-8 로 넘김(ggml 이 윈도우 넓은 문자로 바꿔 엶). 그래도 못 열면 짧은 경로(8.3) → 영문 연결 폴더 순으로 다시 시도(ascii_path).
import ctypes
import os
import sys
import time

import numpy as np

llama_token = ctypes.c_int32
llama_pos = ctypes.c_int32
llama_seq_id = ctypes.c_int32


class llama_model_params(ctypes.Structure):
    _fields_ = [
        ("devices", ctypes.POINTER(ctypes.c_void_p)),
        ("tensor_buft_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("n_gpu_layers", ctypes.c_int32),
        ("split_mode", ctypes.c_int32),
        ("load_mode", ctypes.c_int32),
        ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.POINTER(ctypes.c_float)),
        ("progress_callback", ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_float, ctypes.c_void_p)),
        ("progress_callback_user_data", ctypes.c_void_p),
        ("kv_overrides", ctypes.POINTER(ctypes.c_void_p)),
        ("vocab_only", ctypes.c_bool),
        ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool),
        ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool),
        ("load_mtp", ctypes.c_bool),
    ]


class llama_context_params(ctypes.Structure):
    _fields_ = [
        ("n_ctx", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint32),
        ("n_ubatch", ctypes.c_uint32),
        ("n_seq_max", ctypes.c_uint32),
        ("n_rs_seq", ctypes.c_uint32),
        ("n_outputs_max", ctypes.c_uint32),
        ("n_outputs_max_per_seq", ctypes.c_uint32),
        ("n_threads", ctypes.c_int32),
        ("n_threads_batch", ctypes.c_int32),
        ("ctx_type", ctypes.c_int32),
        ("rope_scaling_type", ctypes.c_int32),
        ("pooling_type", ctypes.c_int32),
        ("attention_type", ctypes.c_int32),
        ("flash_attn_type", ctypes.c_int32),
        ("rope_freq_base", ctypes.c_float),
        ("rope_freq_scale", ctypes.c_float),
        ("yarn_ext_factor", ctypes.c_float),
        ("yarn_attn_factor", ctypes.c_float),
        ("yarn_beta_fast", ctypes.c_float),
        ("yarn_beta_slow", ctypes.c_float),
        ("yarn_orig_ctx", ctypes.c_uint32),
        ("defrag_thold", ctypes.c_float),
        ("cb_eval", ctypes.c_void_p),
        ("cb_eval_user_data", ctypes.c_void_p),
        ("type_k", ctypes.c_int32),
        ("type_v", ctypes.c_int32),
        ("abort_callback", ctypes.c_void_p),
        ("abort_callback_data", ctypes.c_void_p),
        ("embeddings", ctypes.c_bool),
        ("offload_kqv", ctypes.c_bool),
        ("no_perf", ctypes.c_bool),
        ("op_offload", ctypes.c_bool),
        ("swa_full", ctypes.c_bool),
        ("kv_unified", ctypes.c_bool),
        ("samplers", ctypes.POINTER(ctypes.c_void_p)),
        ("n_samplers", ctypes.c_size_t),
        ("ctx_other", ctypes.c_void_p),
    ]


class llama_sampler_chain_params(ctypes.Structure):
    _fields_ = [("no_perf", ctypes.c_bool)]


class llama_batch(ctypes.Structure):
    _fields_ = [
        ("n_tokens", ctypes.c_int32),
        ("token", ctypes.POINTER(llama_token)),
        ("embd", ctypes.POINTER(ctypes.c_float)),
        ("pos", ctypes.POINTER(llama_pos)),
        ("n_seq_id", ctypes.POINTER(ctypes.c_int32)),
        ("seq_id", ctypes.POINTER(ctypes.POINTER(llama_seq_id))),
        ("logits", ctypes.POINTER(ctypes.c_int8)),
    ]


class _Lib:
    """읽은 DLL 과 함수 묶음(한 프로세스에 하나)."""
    llama = None
    folder = ""
    devices = []          # [(이름, 설명)] — 불칸 장치 목록(ggml 이 찾은 것)
    log_lines = []


L = _Lib()
_LOG_KEEP = 200


def _log_cb(level, message, _user):
    if not message:
        return
    try:
        s = message.decode("utf-8", "replace").strip()
    except Exception:  # noqa: BLE001
        return
    if s and s not in (".",):
        L.log_lines.append(s)
        if len(L.log_lines) > _LOG_KEEP:
            del L.log_lines[: len(L.log_lines) - _LOG_KEEP]


_LOG_CB_T = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
_log_ref = _LOG_CB_T(_log_cb)


def _fn(lib, name, args, res):
    f = getattr(lib, name)
    f.argtypes = args
    f.restype = res
    return f


def ascii_path(p, link_root=""):
    """C 라이브러리가 한글 경로를 못 열 때: 윈도우 짧은 경로(8.3) → 없으면 link_root(영문 폴더) 아래 연결 폴더(접합점)."""
    try:
        p.encode("ascii")
        return p
    except UnicodeEncodeError:
        pass
    if os.name != "nt":
        return p
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
    if 0 < n < 1024:
        try:
            buf.value.encode("ascii")
            return buf.value
        except UnicodeEncodeError:
            pass
    if not link_root:
        return p
    folder, name = (os.path.dirname(p), os.path.basename(p)) if os.path.isfile(p) else (p, "")
    import hashlib
    link = os.path.join(link_root, "m" + hashlib.sha1(folder.encode("utf-8")).hexdigest()[:10])
    try:
        os.makedirs(link_root, exist_ok=True)
        if not os.path.isdir(link):
            import subprocess
            subprocess.run(["cmd", "/c", "mklink", "/J", link, folder], capture_output=True, timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if os.path.isdir(link):
            return os.path.join(link, name) if name else link
    except (OSError, ValueError):
        pass
    return p


def load(folder):
    """folder 의 llama.cpp DLL 을 읽는다(두 번째부터는 아무것도 안 함). → 불칸 장치 목록 [(이름, 설명)]."""
    if L.llama is not None:
        return L.devices
    folder = os.path.abspath(folder)
    if sys.platform == "win32":
        names = ("ggml-base.dll", "ggml.dll", "llama.dll")
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(folder)
    else:
        names = ("libggml-base.so", "libggml.so", "libllama.so")
    for n in names:
        if not os.path.isfile(os.path.join(folder, n)):
            raise FileNotFoundError(f"llama.cpp 파일 없음: {n} (폴더 {folder})")
    base = ctypes.CDLL(os.path.join(folder, names[0]))
    ggml = ctypes.CDLL(os.path.join(folder, names[1]))
    lib = ctypes.CDLL(os.path.join(folder, names[2]))
    _fn(lib, "llama_log_set", [_LOG_CB_T, ctypes.c_void_p], None)(_log_ref, None)
    try:
        _fn(base, "ggml_log_set", [_LOG_CB_T, ctypes.c_void_p], None)(_log_ref, None)
    except AttributeError:
        pass
    # 백엔드(ggml-vulkan·ggml-cpu-*.dll)는 이 폴더에서 찾음. 경로는 UTF-8(한글 폴더 가능). 옛 판이면 폴더로 잠깐 옮겨 읽음.
    try:
        _fn(ggml, "ggml_backend_load_all_from_path", [ctypes.c_char_p], None)(folder.encode("utf-8"))
    except AttributeError:
        cwd = os.getcwd()
        os.chdir(folder)
        try:
            _fn(ggml, "ggml_backend_load_all", [], None)()
        finally:
            os.chdir(cwd)
    _fn(lib, "llama_backend_init", [], None)()
    # 장치 목록(불칸 장치 이름) — 진단용
    devs = []

    def pick(name, args, res):          # 판에 따라 ggml.dll 또는 ggml-base.dll 에 있음
        for owner in (ggml, base):
            if hasattr(owner, name):
                return _fn(owner, name, args, res)
        raise AttributeError(name)
    try:
        cnt = pick("ggml_backend_dev_count", [], ctypes.c_size_t)()
        get = pick("ggml_backend_dev_get", [ctypes.c_size_t], ctypes.c_void_p)
        nm = pick("ggml_backend_dev_name", [ctypes.c_void_p], ctypes.c_char_p)
        ds = pick("ggml_backend_dev_description", [ctypes.c_void_p], ctypes.c_char_p)
        for i in range(int(cnt)):
            d = get(i)
            devs.append(((nm(d) or b"").decode("utf-8", "replace"), (ds(d) or b"").decode("utf-8", "replace")))
    except AttributeError:
        pass
    g = {}
    g["model_default_params"] = _fn(lib, "llama_model_default_params", [], llama_model_params)
    g["model_load_from_file"] = _fn(lib, "llama_model_load_from_file", [ctypes.c_char_p, llama_model_params], ctypes.c_void_p)
    g["model_free"] = _fn(lib, "llama_model_free", [ctypes.c_void_p], None)
    g["model_get_vocab"] = _fn(lib, "llama_model_get_vocab", [ctypes.c_void_p], ctypes.c_void_p)
    g["model_n_embd"] = _fn(lib, "llama_model_n_embd", [ctypes.c_void_p], ctypes.c_int32)
    g["context_default_params"] = _fn(lib, "llama_context_default_params", [], llama_context_params)
    g["init_from_model"] = _fn(lib, "llama_init_from_model", [ctypes.c_void_p, llama_context_params], ctypes.c_void_p)
    g["free"] = _fn(lib, "llama_free", [ctypes.c_void_p], None)
    g["batch_init"] = _fn(lib, "llama_batch_init", [ctypes.c_int32, ctypes.c_int32, ctypes.c_int32], llama_batch)
    g["batch_free"] = _fn(lib, "llama_batch_free", [llama_batch], None)
    g["decode"] = _fn(lib, "llama_decode", [ctypes.c_void_p, llama_batch], ctypes.c_int32)
    g["get_logits_ith"] = _fn(lib, "llama_get_logits_ith", [ctypes.c_void_p, ctypes.c_int32], ctypes.POINTER(ctypes.c_float))
    g["get_embeddings"] = _fn(lib, "llama_get_embeddings", [ctypes.c_void_p], ctypes.POINTER(ctypes.c_float))
    g["vocab_n_tokens"] = _fn(lib, "llama_vocab_n_tokens", [ctypes.c_void_p], ctypes.c_int32)
    g["get_memory"] = _fn(lib, "llama_get_memory", [ctypes.c_void_p], ctypes.c_void_p)
    g["memory_clear"] = _fn(lib, "llama_memory_clear", [ctypes.c_void_p, ctypes.c_bool], None)
    g["sampler_chain_default_params"] = _fn(lib, "llama_sampler_chain_default_params", [], llama_sampler_chain_params)
    g["sampler_chain_init"] = _fn(lib, "llama_sampler_chain_init", [llama_sampler_chain_params], ctypes.c_void_p)
    g["sampler_chain_add"] = _fn(lib, "llama_sampler_chain_add", [ctypes.c_void_p, ctypes.c_void_p], None)
    g["sampler_init_greedy"] = _fn(lib, "llama_sampler_init_greedy", [], ctypes.c_void_p)
    g["sampler_init_dist"] = _fn(lib, "llama_sampler_init_dist", [ctypes.c_uint32], ctypes.c_void_p)
    g["sampler_init_temp"] = _fn(lib, "llama_sampler_init_temp", [ctypes.c_float], ctypes.c_void_p)
    g["sampler_init_top_k"] = _fn(lib, "llama_sampler_init_top_k", [ctypes.c_int32], ctypes.c_void_p)
    g["sampler_init_top_p"] = _fn(lib, "llama_sampler_init_top_p", [ctypes.c_float, ctypes.c_size_t], ctypes.c_void_p)
    g["sampler_init_penalties"] = _fn(lib, "llama_sampler_init_penalties",
                                      [ctypes.c_int32, ctypes.c_int32, ctypes.c_float, ctypes.c_float, ctypes.c_float], ctypes.c_void_p)
    g["sampler_sample"] = _fn(lib, "llama_sampler_sample", [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int32], llama_token)
    g["sampler_accept"] = _fn(lib, "llama_sampler_accept", [ctypes.c_void_p, llama_token], None)
    g["sampler_free"] = _fn(lib, "llama_sampler_free", [ctypes.c_void_p], None)
    L.g = g
    L.llama, L.folder, L.devices = lib, folder, devs
    return devs


def gpu_devices():
    """불칸 같은 그래픽 장치 이름(CPU 제외)."""
    return [d for d in L.devices if not d[0].upper().startswith("CPU")]


class Model:
    def __init__(self, path, use_gpu=True, link_root=""):
        g = L.g
        prm = g["model_default_params"]()
        prm.n_gpu_layers = -1 if use_gpu else 0
        if not use_gpu:
            self._nodev = (ctypes.c_void_p * 1)(None)     # 장치 목록 = 비어 있음 → CPU 만
            prm.devices = self._nodev
        self.path = path
        ptr = g["model_load_from_file"](path.encode("utf-8"), prm)
        if not ptr:
            alt = ascii_path(path, link_root)
            if alt != path:
                ptr = g["model_load_from_file"](alt.encode("utf-8"), prm)
                self.path = alt
        if not ptr:
            tail = " | ".join(L.log_lines[-4:])
            raise RuntimeError(f"llama.cpp 가 모델을 못 엶: {os.path.basename(path)} ({tail[-300:]})")
        self.ptr = ptr
        self.vocab = g["model_get_vocab"](ptr)
        self.n_embd = g["model_n_embd"](ptr)
        self.n_vocab = g["vocab_n_tokens"](self.vocab)

    def close(self):
        if getattr(self, "ptr", None):
            L.g["model_free"](self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


class Context:
    def __init__(self, model, n_ctx=2048, n_batch=2048, n_ubatch=512, embeddings=False, threads=None, flash_attn=True):
        g = L.g
        self.model = model
        p = g["context_default_params"]()
        p.n_ctx, p.n_batch, p.n_ubatch, p.n_seq_max = n_ctx, n_batch, n_ubatch, 1
        p.embeddings = embeddings
        p.pooling_type = 0
        p.flash_attn_type = 1 if flash_attn else 0
        p.offload_kqv = True
        p.no_perf = True
        n = int(threads or max(1, (os.cpu_count() or 4) // 2))
        p.n_threads = n
        p.n_threads_batch = n
        self.ptr = g["init_from_model"](model.ptr, p)
        if not self.ptr:
            raise RuntimeError("llama.cpp 문맥(context)을 못 만듦")

    def decode(self, batch):
        return L.g["decode"](self.ptr, batch.struct)

    def logits_ith(self, i):
        return L.g["get_logits_ith"](self.ptr, i)

    def embeddings(self):
        return L.g["get_embeddings"](self.ptr)

    def clear(self):
        L.g["memory_clear"](L.g["get_memory"](self.ptr), True)

    def close(self):
        if getattr(self, "ptr", None):
            L.g["free"](self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


class Batch:
    def __init__(self, n_tokens, embd_dim):
        self.struct = L.g["batch_init"](n_tokens, embd_dim, 1)
        self.n_max = n_tokens

    def set_embd(self, data, pos=0, seq_id=0):
        """data [n, dim] float32 · pos = 시작 번호(int) 또는 위치 배열(Qwen3 다중 평면)."""
        n = data.shape[0]
        if n > self.n_max:
            raise ValueError(f"묶음 자리 모자람: {n} > {self.n_max}")
        data = np.ascontiguousarray(data, dtype=np.float32)
        ctypes.memmove(self.struct.embd, data.ctypes.data, data.nbytes)
        if isinstance(pos, int):
            for i in range(n):
                self.struct.pos[i] = pos + i
        else:
            pos = np.ascontiguousarray(pos, dtype=np.int32)
            ctypes.memmove(self.struct.pos, pos.ctypes.data, pos.nbytes)
        self.struct.n_tokens = n
        for i in range(n):
            self.struct.n_seq_id[i] = 1
            self.struct.seq_id[i][0] = seq_id
            self.struct.logits[i] = 1 if i == n - 1 else 0
        return self

    def close(self):
        if getattr(self, "struct", None) is not None:
            L.g["batch_free"](self.struct)
            self.struct = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass


class Sampler:
    """원본과 같은 순서: (벌점) → top-k → top-p → 온도 → 뽑기. 온도 0 이면 가장 높은 것."""

    def __init__(self, temperature=0.8, top_k=50, top_p=1.0, repeat_penalty=1.0, penalty_last_n=64, seed=None, n_vocab=0):
        g = L.g
        if seed is None:
            seed = int(time.time())
        self.ptr = g["sampler_chain_init"](g["sampler_chain_default_params"]())
        if repeat_penalty != 1.0:
            g["sampler_chain_add"](self.ptr, g["sampler_init_penalties"](n_vocab, penalty_last_n, repeat_penalty, 0.0, 0.0))
        if temperature > 0:
            if top_k > 0:
                g["sampler_chain_add"](self.ptr, g["sampler_init_top_k"](int(top_k)))
            if top_p < 1.0:
                g["sampler_chain_add"](self.ptr, g["sampler_init_top_p"](float(top_p), 1))
            g["sampler_chain_add"](self.ptr, g["sampler_init_temp"](float(temperature)))
            g["sampler_chain_add"](self.ptr, g["sampler_init_dist"](int(seed) & 0xFFFFFFFF))
        else:
            g["sampler_chain_add"](self.ptr, g["sampler_init_greedy"]())

    def accept(self, tok):
        L.g["sampler_accept"](self.ptr, int(tok))

    def sample(self, ctx, idx=-1, limit=None, allow=()):
        """limit=(시작, 끝) 이면 그 범위(+allow) 밖 값은 지우고 뽑음."""
        if limit is not None:
            nv = ctx.model.n_vocab
            lg = np.ctypeslib.as_array(ctx.logits_ith(idx), shape=(nv,))
            s, e = max(0, limit[0]), min(nv, limit[1])
            keep = lg[s:e].copy()
            extra = [(t, lg[t]) for t in allow if 0 <= t < nv and not (s <= t < e)]
            lg[:] = -1e10
            lg[s:e] = keep
            for t, v in extra:
                lg[t] = v
        return L.g["sampler_sample"](self.ptr, ctx.ptr, idx)

    def close(self):
        if getattr(self, "ptr", None):
            L.g["sampler_free"](self.ptr)
            self.ptr = None

    def __del__(self):
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
