# megatui

LSI/Avago/Broadcom **MegaCli64** に curses ベースの TUI フロントエンドを与えるツール。物理ドライブ・論理ドライブ・コントローラ・BBU・エンクロージャの状態を 4 タブで一覧でき、書き込み系操作(ホットスペア指定、Locate LED、リビルド開始/中止、Patrol Read、構成削除など)も確認ダイアログ越しに発行できる。

```
┌─ MegaTUI · adapter 0 ── F1 Physical Drives  F2 Logical Drives  F3 Adapter+BBU  F4 Enclosures ──┐
│ Slot  Enc   DevId  Size        State                MediaErr  OtherErr  Temp  Type  Inquiry      │
│ 0     252   0      1.818 TB    ● Online, Spun Up    0         0         38C   HDD   HGST HUS… │
│ 1     252   1      1.818 TB    ● Online, Spun Up    0         0         39C   HDD   HGST HUS… │
│ 2     252   2      1.818 TB    ◐ Rebuild            12        4         42C   HDD   HGST HUS… │
│ 3     252   3      1.818 TB    ✗ Failed             47        23        --    HDD   HGST HUS… │
│ 4     252   4      1.818 TB    ★ Hotspare           0         0         32C   HDD   HGST HUS… │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
 ↑↓ select   Tab/Shift-Tab tab   F1-F4 jump   Enter detail   a action   r refresh   q quit
```

## 特徴 / Features

- **4 タブ** PD / LD / Adapter+BBU / Enclosure を `F1`〜`F4` で切替
- **状態の色分け** Online=緑、Rebuild=黄、Failed=赤、Hotspare=シアン、温度しきい値で警告
- **詳細モーダル** `Enter` でカーソル行の全フィールドをポップアップ表示
- **40 アクション** (PD 15 / LD 14 / Adapter 11) を 4 段階の危険度でラベリング
  - `safe` … 状態問い合わせ系
  - `write` … 設定変更 (キャッシュポリシー、ホットスペア指定、Patrol Read 起動 など)
  - `destructive` … リビルド中止、PD オフラインなど冗長性が落ちる操作
  - `catastrophic` … `PD Clear`、`LD Delete`、`CfgClr` など破壊操作。**正確な確認語句のタイプ入力**を強制
- **コマンドプレビュー** 実行直前に組み立てた MegaCli64 引数をフル表示してから確認
- **監査ログ** すべての書き込み操作を `~/.local/share/megatui/audit.log` に追記
- **dry-run モード** `MEGATUI_FIXTURES=DIR` または `--fixtures DIR` で MegaCli を呼ばずに UI 検証可
- **依存ゼロ** Python 標準ライブラリ (`curses`) のみ

## 動作要件 / Requirements

- Linux (curses 動作環境)
- Python 3.10 以降
- `/opt/MegaRAID/MegaCli/MegaCli64` (LSI 純正 MegaCli)
- `sudo -n` で MegaCli64 を呼べる権限 (パスワード無し)、または `--no-sudo` 指定可能な環境

## インストール / Install

```bash
git clone <this-repo> megatui
cd megatui
# 依存パッケージは標準ライブラリのみ。インストール作業は不要。
./megatui.sh
```

`megatui.sh` は `python3 -m megatui` を呼ぶラッパ。任意の場所からシンボリックリンクを張ってもよい:

```bash
sudo ln -s "$(pwd)/megatui.sh" /usr/local/bin/megatui
```

## 起動 / Run

```bash
# 通常 (sudo で MegaCli64 を実行)
./megatui.sh

# sudo なし (root で起動するか、MegaCli64 が一般ユーザーで動く環境)
./megatui.sh --no-sudo

# dry-run / オフライン検証 (実機なしでも UI を試せる)
./megatui.sh --fixtures fixtures
```

## キーバインド / Keymap

| キー | 動作 |
| --- | --- |
| `F1`〜`F4` / `1`〜`4` | タブ切替 (PD / LD / Adapter+BBU / Enclosure) |
| `Tab` / `Shift-Tab` | 次/前タブ |
| `↑` `↓` / `j` `k` | カーソル移動 |
| `Home` / `End` | 先頭・末尾 |
| `PgUp` / `PgDn` | 10 行ジャンプ |
| `Enter` | 選択行の詳細モーダルを開く |
| `a` | 選択対象に対するアクションメニュー |
| `r` | 再取得 (PDList / LDInfo / AdpAllInfo / EncInfo / BBU を順に発行) |
| `q` / `Esc` | モーダル閉じる / 終了 |

## 危険度ラベル / Danger ratings

| ラベル | 意味 | 確認方式 |
| --- | --- | --- |
| ` safe ` | データ損失なし。Locate LED, ShowProg 等 | `Y` / Enter |
| ` write` | 状態変更 (キャッシュポリシー、HSP 指定、Patrol Read 開始 等) | `Y` / Enter |
| `DANGER` | 冗長性が落ちる、I/O が中断する (PDOffline, Mark Missing, Init 開始, リビルド中止) | `Y` / Enter |
| `DESTROY` | データ消失または構成破壊 (PD Clear, LD Delete, CfgClr) | **指定キーワードを正確タイプ** |

破壊操作の確認語句:

| アクション | 入力すべき語句 |
| --- | --- |
| PD Clear (`-PDClear -Start`) | `WIPE` |
| LD Delete (`-CfgLdDel -Lx`) | `DELETE` |
| Delete ALL LDs (`-CfgLdDel -LALL`) | `DELETE-ALL` |
| Clear Config (`-CfgClr`) | `CLEAR-CONFIG` |

## 監査ログ / Audit log

書き込み系の試行はすべて 1 行 / 操作で追記される。tab 区切り。

```
2026-05-08T17:28:35+0900	DRYRUN:locate_on	rc=0	/opt/MegaRAID/MegaCli/MegaCli64 -PdLocate -start -PhysDrv [0:0] -a0 -NoLog	target=PD slot=- enc=- dev=0 state=-
2026-05-08T17:30:12+0900	hsp_set	rc=0	sudo -n /opt/MegaRAID/MegaCli/MegaCli64 -PDHSP -Set -PhysDrv [252:4] -a0 -NoLog	target=PD slot=4 ... | Adapter 0: Set Global Hotspare Succeeded.
```

- 場所: `${XDG_DATA_HOME:-~/.local/share}/megatui/audit.log`
- 上書き: `MEGATUI_AUDIT_LOG=/path/to/file` で任意指定
- フィクスチャモードのアクションは `DRYRUN:` プリフィクス付きで記録

## アーキテクチャ / Architecture

```
megatui/
├── megatui.sh          # ./megatui.sh ランチャー
├── megatui/
│   ├── __main__.py     # CLI エントリポイント
│   ├── runner.py       # MegaCli64 サブプロセスラッパ (sudo / fixture replay)
│   ├── parsers.py      # PDList / LDInfo / AdpAllInfo / EncInfo / BBU パーサ
│   ├── actions.py      # 39 アクションの引数組み立て + 危険度メタデータ
│   ├── audit.py        # 監査ログ追記
│   └── tui.py          # curses メインアプリ (App / 描画 / モーダル)
├── fixtures/           # 実機・合成出力サンプル (dry-run と回帰用)
└── tests/
    └── test_parsers.py # パーサ回帰テスト (実機 + 合成)
```

設計メモ:

- パーサは「未知のキーは `raw` dict にそのまま落とす」方針。アクセサ (`pd.state`, `ld.size`) は便利関数。詳細モーダルは `raw` をそのまま全表示するので、ファームウェア更新で新フィールドが増えても情報は失われない。
- PD ヘッダ行は `Enclosure Device ID:` を境界とする (HDD)。テープのように `Device Id:` しか持たない疎なエントリも切り分けられるよう分岐済み。
- BBU は同名キー (`Voltage`, `Temperature`) が外側ブロックとファーム内部ブロックの両方に出現するため、**先勝ち** (`setdefault`) で値を確定し、画面の見出し用には外側のものを使う。

## フィクスチャ / Fixtures

`fixtures/` には以下が同梱:

| ファイル | 内容 |
| --- | --- |
| `pdlist.txt` | 実機 (LSI 9261-8i + テープ 2 台) の PDList |
| `ldinfo.txt` | 同上 — VD なし |
| `adpinfo.txt` | 同上 — `AdpAllInfo` |
| `encinfo.txt` | 同上 — Enclosure (SGPIO) |
| `bbu.txt` | 同上 — BBU 不在 |
| `pdlist_hdd.txt` | 合成: 5 台 HDD (Online x2, Rebuild, Failed, Hotspare) |
| `ldinfo_raid5.txt` | 合成: RAID5 + RAID1 Degraded |
| `bbu_present.txt` | 合成: BBU 正常 (Optimal, 100%) |

回帰テスト:

```bash
python3 tests/test_parsers.py
```

## 開発の進め方 / Development

実機がない環境でも UI を触れる:

```bash
./megatui.sh --fixtures fixtures
```

実機の出力が現状のパーサで欠落するフィールドを見つけたら:

1. `MegaCli64 -PDList -aALL -NoLog > my.txt` などで生出力を取得
2. `fixtures/` に追加
3. `tests/test_parsers.py` にケースを足す
4. `parsers.py` を更新

## 制限 / Known limitations

- MegaCli64 の **読み取り系コマンド (PDList 等) は数百ミリ秒〜数秒** かかる。リフレッシュは同期実行のため、その間 UI はブロックする。
- LD の **新規作成 (`-CfgLdAdd`)** は **単発 RAID0 のみ** TUI から発行可 (PD タブで `Unconfigured(good)` ドライブを選択 → `a` → `Create single-disk RAID0 VD`)。RAID1/5/6 など複数ドライブのアレイ作成は MegaCli の引数仕様が複雑なため意図的に省略。コマンドラインから `MegaCli64 -CfgLdAdd -r1 '[E:S,E:S]' ...` を直接使うこと。なお 1 本 → RAID1 化したい場合は、単発 RAID0 作成後に `MegaCli64 -LDRecon -Start -r1 -Add -PhysDrv '[E:S]' -L<N> -a0` (RAID Level Migration) で 2 本目を追加できる。
- `storcli64` ではなく **MegaCli64 専用**。新しめのコントローラ (12Gb 以降) では storcli を使うべき。

## ライセンス / License

MIT License — `LICENSE` を参照。
