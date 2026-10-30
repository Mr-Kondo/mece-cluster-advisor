# 出力の読み方

`scripts/mece_cluster.py` が出す JSON の構造と、指標の意味を説明する。結果を読む前に目を通す。

## 目次

- 読む順序
- 項目の一覧
- 指標の意味
- 例
- 以前の指標を使わない理由

## 読む順序

1. `meta.warnings`
2. `meta.k`、`meta.k_selection`、`meta.silhouette_mean`
3. `clusters`
4. `boundary_pairs`
5. 必要な項目だけ `items`

## 項目の一覧

### meta

| 項目 | 内容 |
|---|---|
| `n_items` | 項目の数 |
| `k` | グループの数 |
| `k_selection` | `auto` のときだけ。試した k ごとの silhouette 平均。`--k` を指定したときは `null` |
| `silhouette_mean` | 全項目の silhouette の平均 |
| `warnings` | 根拠が弱い選択の警告。自動で選んだ k が探索範囲の上限、1件だけのグループ、など。k を自動で選んだとき(`k_selection` があるとき)は、「実際の話題の数より小さい k を選びやすい」という注意が常に入る |
| `model` / `prefix` | 使った埋め込みモデルと、入力に付けた接頭辞 |
| `device` | 埋め込み計算に使ったデバイス(`cuda`, `mps`, `xpu`, `dml`, `npu`, `cpu` など) |
| `tokenizer` | `sudachi` なら、キーワードは形態素解析による。`regex` なら、日本語が語に分かれていないので、キーワードは参考にとどめる |
| `seed` | 乱数の種。同じ入力と設定なら、同じ結果になる |

### clusters

| 項目 | 内容 |
|---|---|
| `id` | グループの番号 |
| `size` | 項目の数 |
| `silhouette_mean` | グループ内の silhouette の平均 |
| `boundary_count` | 境界にある項目の数 |
| `keywords` | 他のグループより目立つ名詞(最大8語) |
| `representatives` | 重心に最も近い3項目。`index` と原文 |

### boundary_pairs

境界の項目を、「どのグループから(`from`)、どのグループへ(`to`)寄っているか」で数えた一覧。`count` の多い順に並ぶ。

| 項目 | 内容 |
|---|---|
| `from` / `to` | 項目が属するグループと、次に入りそうなグループ |
| `count` | その組の境界項目の数 |
| `items` | silhouette が低い順に最大5件。`index`、原文、`silhouette` |

### items

全項目について、次を持つ。

| 項目 | 内容 |
|---|---|
| `index` | 入力の0始まりの番号(空行を除く) |
| `text` | 原文 |
| `cluster` | 属するグループ |
| `silhouette` | その項目の silhouette |
| `neighbor_cluster` | 次に入りそうなグループ |
| `boundary` | silhouette が 0 以下なら `true` |

### limits

この出力で判定できないことの一覧。報告に反映する。

## 指標の意味

- **silhouette**(Rousseeuw, 1987)。項目ごとに、2つの平均距離を求める。a は同じグループの項目まで、b は最も近い他のグループまでである。silhouette は (b − a) / max(a, b) で、-1 から 1 の値になる。低いほど、別のグループに近い。距離は、コサイン距離である。
- **境界**。silhouette が 0 以下の項目。自分のグループより、他のグループに近いか、同じ程度に近い。
- **neighbor_cluster**。b を与えるグループ。境界の項目が、次に入りそうなグループである。
- **keywords**。SudachiPy で名詞だけを取り、数、代名詞、形式名詞、助数詞を除く。グループごとに項目をまとめて1つの文書とみなし、TF-IDF の高い順に並べる。
- **representatives**。グループの重心に近い順の3項目。グループの典型例である。

絶対的な合格ラインはない。正解が分かっている3テーマ18件を、k=3 で完全に分けても、silhouette の平均は 0.18 だった。

## 例

抜粋である。機械学習の題目20件を `--k 4` で実行した実測値で、`…` は省略を示す。

```json
{
  "meta": {
    "model": "cl-nagoya/ruri-v3-310m",
    "prefix": "トピック: ",
    "tokenizer": "sudachi",
    "device": "mps",
    "n_items": 20,
    "k": 4,
    "k_selection": null,
    "silhouette_mean": 0.0445,
    "seed": 42,
    "warnings": []
  },
  "clusters": [
    {
      "id": 1,
      "size": 3,
      "silhouette_mean": 0.1235,
      "boundary_count": 0,
      "keywords": ["因果", "解析", "モデル", "時系列", "推論"],
      "representatives": [
        {"index": 13, "text": "時系列データ分析の手法"},
        {"index": 5, "text": "統計解析と確率モデル"},
        …
      ]
    },
    …
  ],
  "boundary_pairs": [
    {
      "from": 2,
      "to": 3,
      "count": 2,
      "items": [
        {"index": 9, "text": "PCAと次元削減の理論", "silhouette": -0.046},
        {"index": 15, "text": "推薦システムの構築方法", "silhouette": -0.0012}
      ]
    },
    …
  ],
  "items": […],
  "limits": […]
}
```

この例の読み方は、次のとおり。

- 平均が 0.0445 と低く、20件が1つの分野に集まっている。グループの境界は、はっきりしていない。
- グループ2とグループ3の間に、境界の項目が2件ある。「PCAと次元削減の理論」は、グループ2に入っているが、グループ3に近い。排他性の判定の対象になる。

## 以前の指標を使わない理由

元になった MECE_Refineder の指標は、このスキルでは使わない。同じデータで測って、情報にならなかったためである。

| 以前の指標 | 結果 | 理由 |
|---|---|---|
| グループ中心どうしのコサイン類似度(閾値 0.3) | E5 で 0.90〜0.97、ruri-v3 で 0.93〜0.96。全6組が「重複」になった | E5 は類似度が 0.7〜1.0 に寄る仕様で、ruri-v3 も近い範囲に寄る。中心間の近さは、項目の重なりでもない |
| カバレッジ(1 − HDBSCAN のノイズ率) | 20件中13〜16件がノイズ | 密度の判定結果であり、漏れの有無を表さない |

代わりに、項目ごとの境界(silhouette が 0 以下)と、その集中する組を使う。相対的な指標なので、モデルが変わっても、閾値を調整する必要がない。
