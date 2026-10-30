# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2.5.4", "scikit-learn>=1.9.1", "sudachipy>=0.7.0", "sudachidict-core>=20261015"]
# ///
"""mece_cluster.py の確認。モデルを使わず、合成した埋め込みで動く。

    uv run scripts/test_mece_cluster.py
"""

import numpy as np

from mece_cluster import (
    AUTO_K_NOTE,
    build_result,
    choose_k,
    cosine_distance,
    embed,
    embedding_prefix,
    load_items,
    make_tokenizer,
    resolve_device,
    silhouette,
    skill_version,
)


def _unit(deg: float) -> list[float]:
    r = np.deg2rad(deg)
    return [np.cos(r), np.sin(r)]


# 0度付近に4件、90度付近に4件、その中間(45度)に1件
EMB = np.array([_unit(d) for d in (0, 3, 6, 9, 90, 93, 96, 99, 45)])
TEXTS = [f"item{i}" for i in range(len(EMB))]


def test_load_items_strips_bullets_and_blanks():
    assert load_items("- a\n\n1. b\n* c\n  \n・d\n") == ["a", "b", "c", "d"]
    assert load_items("1.5倍に増やす\n-5℃以下") == ["1.5倍に増やす", "-5℃以下"]  # 項目の先頭は消さない


def test_load_items_csv_column():
    assert load_items("id,comment\n1,x\n2,y\n", csv_mode=True, column="comment") == ["x", "y"]


def test_tokenizer_keeps_content_nouns_only():
    tokenize, name = make_tokenizer()
    if name != "sudachi":
        return  # SudachiPy が入っていない環境では確認しない
    words = tokenize("圧力鍋で豚の角煮を30分で作る")
    assert "圧力鍋" in words and "角煮" in words
    assert "分" not in words and "30" not in words and "で" not in words


def test_skill_version_is_semver():
    import re

    assert re.fullmatch(r"\d+\.\d+\.\d+", skill_version())


def test_embedding_prefix():
    assert embedding_prefix("cl-nagoya/ruri-v3-310m", None) == "トピック: "
    assert embedding_prefix("intfloat/multilingual-e5-base", None) == "query: "
    assert embedding_prefix("all-MiniLM-L6-v2", None) == ""
    assert embedding_prefix("cl-nagoya/ruri-v3-310m", "") == ""


def test_choose_k_finds_two_groups():
    assert choose_k(EMB, cosine_distance(EMB), k_max=4, seed=0)[0] == 2


def test_silhouette_marks_mislabeled_item():
    # 45度の項目を、近い0度側ではなく90度側に入れた場合: 負になり、近い他グループは0
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1])
    sil, neighbor = silhouette(cosine_distance(EMB), labels)
    assert sil[8] < 0 and neighbor[8] == 0
    assert sil[:8].min() > 0.5


def test_build_result_is_consistent():
    res = build_result(TEXTS, EMB, k=2, k_max=4, seed=0, meta={}, tokenize=lambda t: [t])
    assert res["meta"]["k"] == 2 and sorted(c["size"] for c in res["clusters"]) == [4, 5]
    assert len(res["items"]) == len(TEXTS)
    # 境界の組に入る項目の数は、境界と判定された項目の数に一致する
    assert sum(p["count"] for p in res["boundary_pairs"]) == sum(it["boundary"] for it in res["items"])
    assert res["meta"]["warnings"] == []


def test_warns_when_auto_k_hits_upper_bound():
    res = build_result(TEXTS, EMB, k=None, k_max=2, seed=0, meta={}, tokenize=lambda t: [t])
    warnings = res["meta"]["warnings"]
    assert res["meta"]["k"] == 2 and any("上限" in w for w in warnings) and len(warnings) == 2


def test_auto_k_warns_that_it_tends_to_run_small():
    auto = build_result(TEXTS, EMB, k=None, k_max=4, seed=0, meta={}, tokenize=lambda t: [t])
    assert AUTO_K_NOTE in auto["meta"]["warnings"]
    fixed = build_result(TEXTS, EMB, k=2, k_max=4, seed=0, meta={}, tokenize=lambda t: [t])
    assert AUTO_K_NOTE not in fixed["meta"]["warnings"]  # 利用者が k を決めたときは出さない


def test_resolve_device_explicit_cpu():
    dev, name = resolve_device("cpu")
    assert str(dev) == "cpu" and name == "cpu"


def test_resolve_device_auto():
    dev, name = resolve_device("auto")
    assert isinstance(name, str) and len(name) > 0


def test_resolve_device_invalid():
    try:
        import torch  # noqa: F401
    except ImportError:
        return  # torch が入っていない環境ではスキップ
    try:
        resolve_device("non_existent_device_123")
    except SystemExit:
        pass
    else:
        raise AssertionError("invalid device should trigger SystemExit")


def test_resolve_device_unavailable_accelerator():
    """torch を差し替えて、利用できないアクセラレータの明示を弾き、使えるものと cpu は通す(torch の有無に依存しない)。"""
    import sys
    from types import SimpleNamespace as NS

    def fake_torch(cuda: bool, mps: bool, xpu: bool):
        return NS(
            device=lambda s: NS(type=s.split(":")[0], index=int(s.split(":")[1]) if ":" in s else None),
            cuda=NS(is_available=lambda: cuda),
            xpu=NS(is_available=lambda: xpu),
            backends=NS(mps=NS(is_available=lambda: mps)),
        )

    saved = sys.modules.get("torch")
    try:
        sys.modules["torch"] = fake_torch(cuda=False, mps=False, xpu=True)
        for pref in ("cuda", "cuda:0", "mps"):
            try:
                resolve_device(pref)
            except SystemExit as e:
                assert "利用できません" in str(e), pref
            else:
                raise AssertionError(f"{pref} should trigger SystemExit")
        assert resolve_device("xpu")[1] == "xpu"  # 使えるものは通す
        assert resolve_device("cpu")[1] == "cpu"
    finally:
        if saved is None:
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = saved


def _stub_torch(cuda=False, mps=False):
    from types import SimpleNamespace as NS

    return NS(
        device=lambda s: NS(type=s.split(":")[0], index=None),
        cuda=NS(is_available=lambda: cuda),
        backends=NS(mps=NS(is_available=lambda: mps)),
    )


def test_embed_auto_falls_back_to_cpu_but_explicit_does_not():
    """auto で選んだ GPU が失敗したら CPU でやり直す。明示したデバイスは失敗のままにする。"""
    import sys
    from types import SimpleNamespace as NS

    class FakeST:
        def __init__(self, model, device):
            self.device = device

        def encode(self, texts, **kw):
            if self.device == "mps":
                raise RuntimeError("unsupported op")
            return np.ones((len(texts), 2))

    saved = {k: sys.modules.get(k) for k in ("torch", "sentence_transformers")}
    try:
        sys.modules["torch"] = _stub_torch(mps=True)
        sys.modules["sentence_transformers"] = NS(SentenceTransformer=FakeST)
        vecs, name = embed(["a", "b"], "m", "", device="auto")
        assert name == "cpu" and vecs.shape == (2, 2)
        try:
            embed(["a"], "m", "", device="mps")
        except RuntimeError:
            pass
        else:
            raise AssertionError("explicit device must not fall back")
        class NoNet(FakeST):
            def __init__(self, model, device):
                raise OSError("offline")

        sys.modules["sentence_transformers"] = NS(SentenceTransformer=NoNet)
        try:
            embed(["a"], "m", "", device="auto")
        except OSError:
            pass
        else:
            raise AssertionError("OSError must not trigger a CPU retry")
    finally:
        for k, v in saved.items():
            sys.modules.pop(k, None) if v is None else sys.modules.__setitem__(k, v)


def test_auto_cpu_hint_when_gpu_tool_present():
    import io
    import sys
    from contextlib import redirect_stderr
    from unittest import mock

    saved = sys.modules.get("torch")
    try:
        sys.modules["torch"] = _stub_torch()
        for found, expect in (("/usr/bin/nvidia-smi", True), (None, False)):
            buf = io.StringIO()
            with mock.patch("shutil.which", return_value=found), mock.patch("sys.platform", "linux"), redirect_stderr(buf):
                assert resolve_device("auto")[1] == "cpu"
            assert ("GPU" in buf.getvalue()) == expect, buf.getvalue()
    finally:
        sys.modules.pop("torch", None) if saved is None else sys.modules.__setitem__("torch", saved)


def test_build_result_includes_device_in_meta():
    res = build_result(
        TEXTS,
        EMB,
        k=2,
        k_max=4,
        seed=0,
        meta={"model": "dummy", "prefix": "", "tokenizer": "regex", "device": "xpu"},
        tokenize=lambda t: [t],
    )
    assert res["meta"]["device"] == "xpu"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
