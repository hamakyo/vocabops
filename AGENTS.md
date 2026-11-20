# AGENTS.md

## 目的

ソフトウェアエンジニア向けのオープンなコーパス駆動英語語彙プロジェクト（VocabOps）のコード・スキーマ・マニフェスト・公開語彙データの正本。語彙データセット・FSRS 学習エンジン・習慣化レイヤーの3層を段階的に構築する。

## 正本と生成物

- 正本：
  - パイプラインコード・テスト：`src/vocabops/`、`tests/`、`pyproject.toml`
  - 自作フィクスチャコーパス：`data/fixtures/<name>/`
  - 設計・評価ドキュメント：`docs/`（`data-schema.md`、`pipeline-conventions.md`、`architecture.md`、`release-policy.md`、`ranking-evaluation.md`、`core500-evaluation.md` 等）
  - スナップショットマニフェスト：`corpus/manifests/<snapshot-id>.json`
  - 公開語彙データ：`data/releases/<dataset-version>/`
- 生成物（**手で編集しない**）：
  - `out/` 配下のローカルパイプライン出力（`ranking.json`、`ranking.csv`、`manifest.json` 等。gitignore 対象）
  - リポジトリ外の作業領域に置く生コーパス・正規化コーパス・中間ファイル（`raw/`、`normalized/`、`work/`）

## スキーマ

詳細は [docs/data-schema.md](docs/data-schema.md) と [docs/pipeline-conventions.md](docs/pipeline-conventions.md) を正とする。

- 語彙レコードの安定 ID：`<lemma>.<pos>` 形式（例：`retrieve.v`、`fallback.n`、`deterministically.adv`）。再利用禁止。意味を後から分離する場合は既存 ID を変えず意味サフィックスを足す。
- 必須フィールド：`id`・`term`・`lemma`・`pos`（`noun` / `verb` / `adjective` / `adverb` / `phrase` / `other`）・`ja`（`gloss`、`software_gloss`）・`categories`・`provenance`（`dataset_version`、`metric_snapshot`、`sources`）。
- コーパス計測指標：`frequency`・`document_frequency`・`se_specificity`・`llm_lift`・`model_lift`（`claude` / `gpt` / `gemini`）。計測が揃う前は `null` のままにし、人手で `llm-native` ラベルを決め打ちしない。
- ドキュメント ID：`sha256(source_family + "/" + relative_path)` の 16進ダイジェスト（ファイルパスが無いソースは `gharchive/<event id>` のようにソース固有の安定 ID をハッシュする）。
- バージョニング：破壊的スキーマ変更はデータセットのメジャーバージョンを上げる。人手編集と生成指標の区別を保つ。

## 更新の流れ

1. 仮想環境（Python 3.11+、`.venv/`）と `pyproject.toml` の依存を使う（アドホックなインストールはしない）
   ```sh
   python3 -m venv .venv
   .venv/bin/pip install -e ".[dev]"
   ```
2. コード・フィクスチャ・ドキュメントを編集する
3. 再現性あるコマンド（固定 `--snapshot-id` 指定）でパイプラインを実行し、テスト（`.venv/bin/pytest`）がすべて通ることを確認する
   ```sh
   .venv/bin/python -m vocabops.pipeline \
     --input data/fixtures/sample_corpus \
     --output out/human-se-v0.1-proto \
     --snapshot-id human-se-v0.1-proto
   ```
4. 公開してよいファイル（コード・テスト・自作フィクスチャ・マニフェスト・集計統計・公開語彙・ドキュメント）だけを commit & push する

## 禁止事項

- 第三者コーパスの生テキスト（Stack Overflow、GH Archive、CodeSearchNet 等）や、そこから作った正規化ドキュメント・大容量中間ファイル・`out/` の commit
- 秘密情報（API キー・トークン等）の記録（保存場所だけを書く）
- 非決定的なパイプライン処理の導入（時刻・ホスト名依存のスナップショット ID、ファイルシステム順・ハッシュマップ順に依存する出力、ランキング行へのタイムスタンプ混入）
- 計測根拠のない `llm-native` 認定や `id` の再利用
- `wordfreq` 等のベースライン変更をマニフェストやリリースノートに記録せず混ぜること

## 除外・対象外

- 公開 repo のため、個人の学習履歴や私的メモ・個人情報はここに入れない。
- 著作権のある外部コーパス本文の再配布は行わず、派生語彙データと集計統計のみを公開対象とする。
