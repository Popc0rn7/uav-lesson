"""AeroVLA NPU runner: vision + chunked prefill + greedy decode on Houmo xh2.

KV cache handoff follows the official houmo modelzoo pattern (laguna demo):
prefill and decode are loaded with a shared WeightManager; decode's cache
inputs are dummy tensors bound to prefill's device-side cache pointers.
"""
import json, os, re, sys
sys.path.insert(0, os.environ.get("TCIM_PYTHON_DIR", "/data/local/houmo/python"))
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.environ.get("AEROVLA_MODEL_ROOT", ROOT)
ASSETS = os.path.join(MODEL_ROOT, "assets")
MODELS = os.path.join(MODEL_ROOT, "models")


def _set(model, key, arr):
    for i in range(model.get_num_inputs()):
        n = model.get_input_name(i)
        if key in n.lower() and "cache" not in n.lower():
            model.set_input(n, arr.astype(model.get_input_info(n).dtype))
            return True
    return False


def _logits(model):
    for i in range(model.get_num_outputs()):
        n = model.get_output_name(i)
        if "logit" in n.lower():
            return model.get_output(n).numpy()
    raise RuntimeError("no logits output")


class AeroVLARunner:
    def __init__(self):
        import tcim_lite as tcim
        with open(os.path.join(ASSETS, "assets.json")) as f:
            self.cfg = json.load(f)
        with open(os.path.join(ASSETS, "id2token.json")) as f:
            self.id2token = {int(k): v for k, v in json.load(f).items()}
        self.emb = np.load(os.path.join(ASSETS, "token_embedding.npy"))

        self.vision = tcim.runtime.load(os.path.join(MODELS, "aerovla_vision.hmm"))
        self.vision_in = self.vision.get_input_name(0)

        dm = tcim.runtime.DevManager([0], "Xh2HalBackend")
        wm = tcim.runtime.WeightManager(dm)
        self.prefill = tcim.runtime.load(
            os.path.join(MODELS, "aerovla_prefill.hmm"), option=tcim.runtime.Option(wm))
        self.cache_names = [
            self.prefill.get_input_name(i)
            for i in range(self.prefill.get_num_inputs())
            if "cache" in self.prefill.get_input_name(i).lower()]
        opt = tcim.runtime.Option(wm)
        opt.set_dummy_tensors(self.cache_names)
        self.decode = tcim.runtime.load(
            os.path.join(MODELS, "aerovla_decode.hmm"), option=opt)
        self.CHUNK = self.prefill.get_input_info("input_1").shape[1]
        self.bind_caches()

    def bind_caches(self):
        """Zero prefill caches; alias decode cache inputs to the same device buffers."""
        for n in self.cache_names:
            info = self.prefill.get_input_info(n)
            self.prefill.set_input(n, np.zeros(tuple(info.shape), dtype=np.dtype(info.dtype)))
            self.decode.set_input(n, self.prefill.get_dev_input(n))

    def _vision_embed(self, pixel_values):
        m = self.vision
        m.set_input(self.vision_in, pixel_values.astype(m.get_input_info(self.vision_in).dtype))
        m.run()
        m.sync()
        return m.get_output(m.get_output_name(0)).numpy().astype(np.float16)

    def build_inputs_embeds(self, input_ids, img_emb):
        # Prismatic convention: patch embeddings inserted right after BOS token
        ids = list(input_ids)
        return np.concatenate([self.emb[ids[:1]], img_emb[0], self.emb[ids[1:]]], axis=0)

    def generate(self, input_ids, pixel_values):
        if not input_ids or any(type(t) is not int or not 0 <= t < self.cfg["vocab_size"] for t in input_ids):
            raise ValueError("input_ids 超出 embedding 词表")
        img_emb = self._vision_embed(pixel_values)
        seq = self.build_inputs_embeds(input_ids, img_emb)
        total = seq.shape[0]
        if total + self.cfg["max_new_tokens"] > 1024:
            raise ValueError("输入与生成预算超过当前模型 1024-token KV cache")
        self.bind_caches()

        logits = None
        n_chunks = max(1, (total + self.CHUNK - 1) // self.CHUNK)
        for ci in range(n_chunks):
            part = seq[ci * self.CHUNK:(ci + 1) * self.CHUNK]
            valid = part.shape[0]
            if valid < self.CHUNK:
                part = np.concatenate(
                    [part, np.repeat(self.emb[32000][None, :], self.CHUNK - valid, 0)], 0)
            pos = np.concatenate([np.arange(ci * self.CHUNK, ci * self.CHUNK + valid),
                                  np.ones(self.CHUNK - valid, np.int64)]).reshape(1, self.CHUNK)
            _set(self.prefill, "input_1", part[None])
            _set(self.prefill, "current_length", np.array([valid], np.int32))
            _set(self.prefill, "valid", np.array([ci * self.CHUNK], np.int32))
            _set(self.prefill, "position", pos)
            self.prefill.run()
            self.prefill.sync()
            logits = _logits(self.prefill)

        token = int(np.argmax(logits[0, 0, :self.cfg["vocab_size"]]))
        eos = self.cfg["eos_token_id"]
        if token == eos:
            return []
        gen = [token]
        for i in range(self.cfg["max_new_tokens"] - 1):
            p = total + i
            _set(self.decode, "input_1", self.emb[token][None, None, :])
            _set(self.decode, "current_length", np.array([1], np.int32))
            _set(self.decode, "valid", np.array([p], np.int32))
            _set(self.decode, "position", np.array([[p]], np.int64))
            self.decode.run()
            self.decode.sync()
            token = int(np.argmax(_logits(self.decode)[0, 0, :self.cfg["vocab_size"]]))
            if token == eos:
                break
            gen.append(token)
        return gen

    def parse_action(self, gen_ids):
        text = "".join(self.id2token.get(t, "") for t in gen_ids)
        part = text.split("Action:")[-1]
        m = re.findall(r"\d+", part)
        fwd = down = yaw = 0.0
        if len(m) >= 3:
            nb = self.cfg["num_bins"]
            def dq(b, axis):
                lo, hi = self.cfg["norm_stats"][axis]
                b = max(0, min(nb - 1, b))
                return b / (nb - 1) * (hi - lo) + lo
            fwd, down, yaw = dq(int(m[-3]), "forward"), dq(int(m[-2]), "down"), dq(int(m[-1]), "yaw")
        land = ("LAND" in text) or (len(m) >= 3 and abs(fwd) < 0.01 and abs(down) < 0.01 and abs(yaw) < 0.01)
        return {"fwd": fwd, "down": down, "yaw": yaw}, bool(land), text
