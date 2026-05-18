"""Lightweight i18n for megatui.

Single source of translations keyed by dotted strings. English is the
default and its values are inlined as `default=` arguments at the call
site (so the source is self-documenting); non-default languages live
in `TRANSLATIONS`.

Language selection (highest priority wins):
    1. set_lang() called explicitly (e.g. from --lang CLI flag)
    2. MEGATUI_LANG environment variable
    3. LC_MESSAGES / LC_ALL / LANG environment variables
    4. default 'en'
"""
from __future__ import annotations

import os


SUPPORTED: tuple[str, ...] = ("en", "ja")

_LANG = "en"


def detect_lang() -> str:
    """Pick a language from env vars; fall back to 'en'."""
    forced = os.environ.get("MEGATUI_LANG")
    if forced:
        for code in SUPPORTED:
            if forced.startswith(code):
                return code
        return "en"
    for var in ("LC_MESSAGES", "LC_ALL", "LANG"):
        v = os.environ.get(var, "")
        for code in SUPPORTED:
            if v.startswith(code):
                return code
    return "en"


def set_lang(code: str) -> None:
    """Force the active language; ignored if not in SUPPORTED."""
    global _LANG
    for c in SUPPORTED:
        if code.startswith(c):
            _LANG = c
            return
    _LANG = "en"


def current_lang() -> str:
    return _LANG


def t(key: str, default: str | None = None, **fmt: object) -> str:
    """Translate `key`. Returns `default` (or `key`) when no entry exists.

    `**fmt` is applied as `.format()` kwargs to the resolved string so
    callers can interpolate values without thinking about which language
    is active. Missing keys never raise — UI strings degrade to their
    English default rather than crashing the TUI.
    """
    table = TRANSLATIONS.get(_LANG, {})
    template = table.get(key)
    if template is None:
        template = default if default is not None else key
    try:
        return template.format(**fmt) if fmt else template
    except (KeyError, IndexError, ValueError):
        return template


# --------------------------------------------------------------------------- #
# Translation tables
# --------------------------------------------------------------------------- #

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ja": {
        # ---- Tabs / chrome ---------------------------------------------- #
        "ui.tab.physical_drives":   "物理ドライブ",
        "ui.tab.logical_drives":    "論理ドライブ",
        "ui.tab.adapter_bbu":       "コントローラ/BBU",
        "ui.tab.enclosures":        "エンクロージャ",

        # ---- Danger tags (2-char Japanese ≈ 4 cells; English uses 6 so
        # the title column starts slightly closer in ja mode — acceptable
        # tradeoff vs ascii-art width fixing).
        "ui.danger.safe":           "安全",
        "ui.danger.write":          "書込",
        "ui.danger.destructive":    "危険",
        "ui.danger.catastrophic":   "破壊",
        # Long form used in the confirm dialog "Danger: X" line
        "ui.danger.safe_full":          "安全 (SAFE)",
        "ui.danger.write_full":         "書込 (WRITE)",
        "ui.danger.destructive_full":   "危険 (DESTRUCTIVE)",
        "ui.danger.catastrophic_full":  "破壊的 (CATASTROPHIC)",

        # ---- Status bar ------------------------------------------------- #
        "ui.status.refreshing":     "更新中…",
        "ui.status.refreshed":      "[{backend}] {time} 更新完了  adapters={adapters} PDs={pds} LDs={lds} Encs={encs}",
        "ui.status.refresh_failed": "更新失敗: {exc}",
        "ui.status.cancelled":      "キャンセルしました。",
        "ui.status.fixture_dry_run":"[fixture モード] 実行されるコマンド: {cmd}",
        "ui.status.ok":             "成功: {title}",
        "ui.status.fail":           "失敗 ({rc}): {title}",

        # ---- Action picker / confirm dialog ----------------------------- #
        "ui.picker.no_actions_title": "アクションなし",
        "ui.picker.no_actions_body":  "この対象に対する利用可能なアクションがありません。",
        "ui.picker.hint":             "[↑↓] 選択  [Enter] 決定  [Esc] キャンセル",
        "ui.confirm.title":           "確認: {title}",
        "ui.confirm.action":          "アクション:",
        "ui.confirm.target":          "対象:",
        "ui.confirm.danger":          "危険度:",
        "ui.confirm.command":         "コマンド:",
        "ui.confirm.typed_phrase":    "確認のため正確にタイプ: '{phrase}'",
        "ui.confirm.prompt":          "確認 > ",
        "ui.confirm.yes_no":          "[Y]es / [N]o",
        "ui.confirm.proceed":         "実行しますか?",

        # ---- Modals ----------------------------------------------------- #
        "ui.modal.fixture_title":   "Fixture モード (空実行)",
        "ui.modal.fixture_line1":   "コマンドは実行されていません。",
        "ui.modal.fixture_line2":   "MEGATUI_FIXTURES を解除すると実機で実行されます。",
        "ui.modal.ok_title":        "成功 — {title}",
        "ui.modal.fail_title":      "失敗 ({rc}) — {title}",
        "ui.modal.no_output":       "(出力なし)",
        "ui.modal.pd_title":        "PD slot={slot} dev={dev}",
        "ui.modal.ld_title":        "LD {idx} ({name})",
        "ui.modal.adp_title":       "コントローラ {idx}",
        "ui.modal.enc_title":       "エンクロージャ {idx}",

        # ---- Empty-list messages --------------------------------------- #
        "ui.empty.pds":             "このコントローラには物理ドライブがありません。",
        "ui.empty.lds":             "論理ドライブ未構成。外部ツールで RAID ボリュームを作成してください。",
        "ui.empty.adp":             "コントローラ情報未取得。[r] で更新してください。",
        "ui.empty.bbu_unloaded":    "未取得です — [r] で更新してください。",
        "ui.empty.bbu_absent":      "未搭載 / 非対応",
        "ui.empty.encs":            "エンクロージャがありません。",

        # ---- Footer / hint --------------------------------------------- #
        "ui.footer.short":          "a アクション   r 更新   q 終了 ",
        "ui.footer.full":           " ↑↓ 選択   Tab/Shift-Tab タブ切替   F1-F4 ジャンプ   Enter 詳細   a アクション   r 更新   q 終了",
        "ui.footer.term_small":     "端末が小さすぎます ({w}x{h}) — 最低 80x12 必要。",

        # ---- BBU section labels ---------------------------------------- #
        "ui.bbu.status":            "状態:",

        # ---- Column headers (PD tab) ----------------------------------- #
        "ui.col.slot":              "スロット",
        "ui.col.enc":               "エンクロージャ",
        "ui.col.devid":             "DevId",
        "ui.col.size":              "容量",
        "ui.col.state":             "状態",
        "ui.col.media_err":         "メディア",
        "ui.col.other_err":         "その他",
        "ui.col.temp":              "温度",
        "ui.col.type":              "種別",
        "ui.col.inquiry":           "Inquiry",
        # (LD tab)
        "ui.col.ld":                "LD",
        "ui.col.name":              "名前",
        "ui.col.raid":              "RAID",
        "ui.col.drives":            "本数",
        "ui.col.strip":             "Strip",
        "ui.col.cache":             "Cache",
        # (Adapter detail)
        "ui.col.adp":               "Adp",
        "ui.col.enc_hash":          "Enc#",
        "ui.col.devid_full":        "DevID",
        "ui.col.slots":             "スロット",
        "ui.col.pds":               "PD数",
        "ui.col.psu":               "PSU",
        "ui.col.fan":               "Fan",
        "ui.col.tempsensors":       "温度センサ",
        "ui.col.status":            "状態",
        "ui.col.vendor_product":    "Vendor/Product",

        # ---- Section headings ------------------------------------------ #
        "ui.section.adapter":       "コントローラ",
        "ui.section.bbu":           "BBU",

        # ---- Adapter field labels -------------------------------------- #
        "ui.adp.serial":            "シリアル",
        "ui.adp.fw_version":        "FW バージョン",
        "ui.adp.fw_package":        "FW パッケージ",
        "ui.adp.bios":              "BIOS",
        "ui.adp.memory":            "メモリ",
        "ui.adp.sas_address":       "SAS アドレス",
        "ui.adp.host_interface":    "ホスト I/F",
        "ui.adp.backend_ports":     "Backend ポート",
        "ui.adp.virtual_drives":    "仮想ドライブ",
        "ui.adp.physical_devices":  "物理ドライブ",
        "ui.adp.disks_failed":      "ディスク (故障)",
        "ui.adp.rebuild_rate":      "リビルド率",
        "ui.adp.pr_rate":           "Patrol Read 率",
        "ui.adp.bgi_rate":          "BGI 率",
        "ui.adp.cc_rate":           "CC 率",
        "ui.adp.auto_rebuild":      "自動リビルド",
        "ui.adp.alarm":             "アラーム",

        # ---- BBU field labels ------------------------------------------ #
        "ui.bbu.state":             "状態",
        "ui.bbu.battery_type":      "種別",
        "ui.bbu.charge":            "充電率",
        "ui.bbu.voltage":           "電圧",
        "ui.bbu.current":           "電流",
        "ui.bbu.temperature":       "温度",
        "ui.bbu.charger_status":    "充電器状態",
        "ui.bbu.remaining":         "残容量",
        "ui.bbu.full_capacity":     "満充電容量",
        "ui.bbu.replacement":       "交換要否",
        "ui.bbu.learn_active":      "Learn 実行中",
        "ui.bbu.learn_status":      "Learn 状態",

        # ---- Action titles --------------------------------------------- #
        "action.locate_on.title":          "Locate LED 点灯",
        "action.locate_off.title":         "Locate LED 消灯",
        "action.rebuild_progress.title":   "リビルド進捗",
        "action.hsp_set.title":            "グローバル Hot Spare に設定",
        "action.hsp_remove.title":         "Hot Spare 解除",
        "action.pd_online.title":          "PD Online",
        "action.pd_make_good.title":       "PD Make Good (Unconfigured Good 化)",
        "action.rebuild_start.title":      "リビルド開始",
        "action.rebuild_stop.title":       "リビルド中止",
        "action.pd_offline.title":         "PD Offline",
        "action.pd_mark_missing.title":    "Missing に印付け",
        "action.pd_make_bad.title":        "PD Make Bad (強制 Failed)",
        "action.pd_clear_progress.title":  "PD Clear 進捗",
        "action.pd_clear.title":           "PD Clear (データ消去)",
        "action.pd_create_r0.title":       "単発 RAID0 VD 作成",
        "action.pd_reformat_512.title":    "セクタを 512 byte に再フォーマット",
        "action.ld_init_progress.title":   "Init 進捗",
        "action.ld_cc_progress.title":     "CC 進捗",
        "action.ld_cc_start.title":        "Consistency Check 開始",
        "action.ld_cc_stop.title":         "Consistency Check 中止",
        "action.ld_set_wb.title":          "Cache: WriteBack",
        "action.ld_set_wt.title":          "Cache: WriteThrough",
        "action.ld_set_ra.title":          "Read: Adaptive ReadAhead",
        "action.ld_set_nora.title":        "Read: No ReadAhead",
        "action.ld_set_cached.title":      "IO: Cached",
        "action.ld_set_direct.title":      "IO: Direct",
        "action.ld_init_start.title":      "Init (Fast)",
        "action.ld_init_full.title":       "Init (FULL)",
        "action.ld_init_stop.title":       "Init 中止",
        "action.ld_delete.title":          "論理ドライブ削除",
        "action.pr_info.title":            "Patrol Read 情報",
        "action.pr_start.title":           "Patrol Read 開始",
        "action.pr_suspend.title":         "Patrol Read 一時停止",
        "action.pr_resume.title":          "Patrol Read 再開",
        "action.pr_stop.title":            "Patrol Read 停止",
        "action.alarm_silence.title":      "アラーム消音",
        "action.alarm_enable.title":       "アラーム有効化",
        "action.alarm_disable.title":      "アラーム無効化",
        "action.bbu_learn.title":          "BBU Learn サイクル開始",
        "action.cfg_delete_all_lds.title": "全 LD 削除",
        "action.cfg_clear.title":          "構成全消去",

        # ---- Action summaries (one line each) -------------------------- #
        "action.locate_on.summary":        "ドライブを物理的に特定するため、スロットの LED を点滅させます。",
        "action.locate_off.summary":       "Locate LED を消灯します。",
        "action.rebuild_progress.summary": "リビルドの進捗率と残時間を表示します。",
        "action.hsp_set.summary":          "このドライブをグローバル Hot Spare に設定します。",
        "action.hsp_remove.summary":       "Hot Spare を解除して Unconfigured Good に戻します。",
        "action.pd_online.summary":        "ドライブを強制 Online にします (firmware が許可する場合のみ)。",
        "action.pd_make_good.summary":     "Foreign / Failed なドライブを Unconfigured Good に戻します。",
        "action.rebuild_start.summary":    "このドライブのリビルドを手動で開始します。",
        "action.rebuild_stop.summary":     "進行中のリビルドを中断します — アレイは Degraded のまま。",
        "action.pd_offline.summary":       "ドライブを強制 Offline にします。冗長性最終ならアレイ停止。",
        "action.pd_mark_missing.summary":  "Missing 印を付けます (replace-missing の前提)。",
        "action.pd_make_bad.summary":      "ドライブを強制 Failed 状態にします。",
        "action.pd_clear_progress.summary":"進行中の PD Clear の進捗を表示します。",
        "action.pd_clear.summary":         "物理ドライブの全内容を初期化 / 消去します。",
        "action.pd_create_r0.summary":     "このドライブを単発 RAID0 LD として登録します (既存データは失われます)。",
        "action.pd_reformat_512.summary":  "sg_format で SCSI FORMAT UNIT を発行。NetApp/Sun/HP 系の 520/528 byte セクタを 512 byte に変換。数時間〜半日、不可逆、全データ消失。",
        "action.ld_init_progress.summary": "Background init / Fast init の進捗を表示します。",
        "action.ld_cc_progress.summary":   "Consistency Check の進捗を表示します。",
        "action.ld_cc_start.summary":      "この LD の Consistency Check を開始します。",
        "action.ld_cc_stop.summary":       "進行中の Consistency Check を中止します。",
        "action.ld_set_wb.summary":        "書き込みポリシーを WriteBack に設定します。",
        "action.ld_set_wt.summary":        "書き込みポリシーを WriteThrough に設定します。",
        "action.ld_set_ra.summary":        "Adaptive Read-Ahead を有効化します。",
        "action.ld_set_nora.summary":      "Read-Ahead を無効化します。",
        "action.ld_set_cached.summary":    "Cached I/O ポリシーを使用します。",
        "action.ld_set_direct.summary":    "Direct I/O ポリシーを使用します (Read 時キャッシュをバイパス)。",
        "action.ld_init_start.summary":    "Fast Initialize: メタデータのみゼロクリア。データは読めなくなります。",
        "action.ld_init_full.summary":     "Full Initialize: 全体をゼロクリア。バックグラウンド実行、不可逆。",
        "action.ld_init_stop.summary":     "進行中の LD Init を中止します。",
        "action.ld_delete.summary":        "この論理ドライブと全データを削除します。",
        "action.pr_info.summary":          "Patrol Read のスケジュールと進捗を表示します。",
        "action.pr_start.summary":         "今すぐ Patrol Read を開始します。",
        "action.pr_suspend.summary":       "実行中の Patrol Read を一時停止します。",
        "action.pr_resume.summary":        "一時停止中の Patrol Read を再開します。",
        "action.pr_stop.summary":          "実行中の Patrol Read を停止します。",
        "action.alarm_silence.summary":    "設定変更せずコントローラのアラームを消音します。",
        "action.alarm_enable.summary":     "コントローラのアラームを有効化します。",
        "action.alarm_disable.summary":    "コントローラのアラームを無効化します。",
        "action.bbu_learn.summary":        "BBU Learn サイクル (容量テスト) を開始します。",
        "action.cfg_delete_all_lds.summary":"このコントローラの全 LD を削除します (データ消失)。",
        "action.cfg_clear.summary":        "RAID 構成 (LD/HSP/Foreign) を全消去します。取り消し不可。",

        # ---- CLI help text (argparse) ---------------------------------- #
        "cli.description": "LSI MegaCli64 / storcli64 / sas3ircu 向け curses TUI (MegaRAID / SAS HBAs)。",
        "cli.backend.help": "使用する CLI バックエンド。'auto' は storcli > MegaCli64 > sas*ircu の順に選択。",
        "cli.no_sudo.help": "バックエンドバイナリ呼び出し時に sudo を付けない。",
        "cli.fixtures.help": "DIR の出力ファイルからリプレイ (オフライン / 空実行モード)。書き込み系は実行されず監査ログに残るのみ。",
        "cli.list_backends.help": "インストール済みバックエンドを表示して終了。",
        "cli.lang.help": "UI 言語 (en, ja)。未指定時は LANG/LC_MESSAGES 環境変数から推定、最終的に 'en'。",
    },
}
