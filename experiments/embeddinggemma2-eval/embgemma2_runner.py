"""EmbeddingGemma 2 (q4f16, text-only) direct ORT runner for the standalone bench.

fastembed 0.8.1 cannot load this model: no registry entry, multi-modal graph inputs
(image/video/audio_features), and the useful output is `sentence_embedding` (output[1]),
not last_hidden_state. This runner is the ONLY honest path: ORT session + rust tokenizer,
prompts from the official config_sentence_transformers.json:
  query:    "task: search result | query: {text}"
  document: "title: none | text: {text}"
Output: sentence_embedding [B,768], already pooled+normalized (norm==1.0 verified).
Truncation clamp: 512 tokens (operational clamp parity).
"""
import os, time, sys
import numpy as np

Q_PREFIX = "task: search result | query: "
D_PREFIX = "title: none | text: "


class EmbGemma2Runner:
    def __init__(self, model_dir: str, model_file: str = "model_q4f16.onnx", threads: int = 2):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(max_length=512)
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        self.sess = ort.InferenceSession(
            os.path.join(model_dir, model_file),
            sess_options=so,
            providers=["CPUExecutionProvider"],
        )

    def embed(self, texts, batch_size: int = 4, doc: bool = False):
        pref = D_PREFIX if doc else Q_PREFIX
        wrapped = [pref + t if pref and not t.startswith(pref) else t for t in texts]
        out = []
        for i in range(0, len(wrapped), batch_size):
            chunk = wrapped[i:i + batch_size]
            encs = self.tok.encode_batch(chunk)
            maxlen = max(len(e.ids) for e in encs)
            ids = np.zeros((len(encs), maxlen), dtype=np.int64)
            mask = np.zeros((len(encs), maxlen), dtype=np.int64)
            for r, e in enumerate(encs):
                ids[r, :len(e.ids)] = e.ids
                mask[r, :len(e.attention_mask)] = e.attention_mask
            emb = self.sess.run(
                ["sentence_embedding"],
                {
                    "input_ids": ids,
                    "attention_mask": mask,
                    "image_features": np.zeros((0, 512), dtype=np.float32),
                    "video_features": np.zeros((0, 512), dtype=np.float32),
                    "audio_features": np.zeros((0, 512), dtype=np.float32),
                },
            )[0]
            out.append(emb)
        return np.concatenate(out, axis=0).astype(np.float32)


if __name__ == "__main__":
    B = os.path.expandvars(r"%LOCALAPPDATA%\jev-mem\bench\run-20261006-embedgemma2")
    r = EmbGemma2Runner(os.path.join(B, "model-src"))
    t0 = time.time()
    e = r.embed(["안녕하세요, 테스트입니다."])
    print("load+first embed s:", round(time.time() - t0, 2))
    print("shape:", e.shape, "norm:", float(np.linalg.norm(e[0]).round(6)))
    e2 = r.embed(["안녕하세요, 테스트입니다."], doc=True)
    print("cos(q,doc-self):", float((e[0] @ e2[0]).round(4)))
    e3 = r.embed(["텔레그램 게이트웨이 수신 문제 해결 방법"])
    e4 = r.embed(["프랑스 파리의 날씨는 어떨까요?"])
    e_rel = r.embed(["게이트웨이 텔레그램 수신 문제"])
    print("cos(q,related):", float((e3[0] @ e_rel[0]).round(4)))
    print("cos(q,unrelated):", float((e3[0] @ e4[0]).round(4)))
    print("RUNNER OK")