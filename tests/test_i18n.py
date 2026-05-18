"""Tests for the i18n shim."""
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import i18n  # noqa: E402


def test_default_lang_is_en() -> None:
    i18n.set_lang("en")
    assert i18n.current_lang() == "en"
    # No "en" entries in TRANSLATIONS; fallback to default kwarg.
    assert i18n.t("ui.tab.physical_drives", default="Physical Drives") == "Physical Drives"


def test_ja_translations_load() -> None:
    i18n.set_lang("ja")
    assert i18n.current_lang() == "ja"
    assert i18n.t("ui.tab.physical_drives", default="Physical Drives") == "物理ドライブ"
    assert i18n.t("ui.tab.logical_drives") == "論理ドライブ"
    assert i18n.t("ui.tab.adapter_bbu") == "コントローラ/BBU"
    assert i18n.t("ui.tab.enclosures") == "エンクロージャ"
    # Reset for other tests.
    i18n.set_lang("en")


def test_t_falls_back_to_default_when_missing() -> None:
    i18n.set_lang("ja")
    # Made-up key — should return the explicit default.
    assert i18n.t("does.not.exist", default="hello") == "hello"
    # No default and no entry → return the key itself (helps debugging).
    assert i18n.t("does.not.exist") == "does.not.exist"
    i18n.set_lang("en")


def test_t_format_substitution() -> None:
    i18n.set_lang("ja")
    out = i18n.t("ui.status.refreshed", time="12:34:56", backend="storcli",
                 adapters=1, pds=3, lds=0, encs=1)
    assert "[storcli]" in out
    assert "12:34:56" in out
    assert "更新完了" in out
    i18n.set_lang("en")


def test_detect_lang_env_priority() -> None:
    saved = {k: os.environ.get(k) for k in ("MEGATUI_LANG", "LC_MESSAGES", "LC_ALL", "LANG")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        # MEGATUI_LANG wins
        os.environ["MEGATUI_LANG"] = "ja"
        os.environ["LANG"] = "C.UTF-8"
        assert i18n.detect_lang() == "ja"
        # without override, LANG=ja_JP.UTF-8 also picks ja
        os.environ.pop("MEGATUI_LANG")
        os.environ["LANG"] = "ja_JP.UTF-8"
        assert i18n.detect_lang() == "ja"
        # no Japanese signal → en
        os.environ["LANG"] = "C.UTF-8"
        assert i18n.detect_lang() == "en"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_action_lookup_falls_back_to_english_default() -> None:
    """If a translation is missing the English Action.title survives."""
    from megatui.actions import PD_ACTIONS
    from megatui.tui import action_title

    i18n.set_lang("ja")
    pd_create = next(a for a in PD_ACTIONS if a.key == "pd_create_r0")
    # ja translation exists for this one
    assert action_title(pd_create) == "単発 RAID0 VD 作成"

    # Fabricate a fake action with no ja key
    from megatui.actions import Action
    fake = Action(
        key="totally_made_up_key",
        title="My Brand New Action",
        danger="safe",
        target="pd",
        summary="x",
    )
    assert action_title(fake) == "My Brand New Action"
    i18n.set_lang("en")


def test_danger_tag_translation() -> None:
    from megatui.tui import danger_tag
    i18n.set_lang("en")
    assert danger_tag("safe") == " safe "
    assert danger_tag("catastrophic") == "DESTROY"
    i18n.set_lang("ja")
    assert danger_tag("safe") == "安全"
    assert danger_tag("catastrophic") == "破壊"
    i18n.set_lang("en")


if __name__ == "__main__":
    test_default_lang_is_en()
    test_ja_translations_load()
    test_t_falls_back_to_default_when_missing()
    test_t_format_substitution()
    test_detect_lang_env_priority()
    test_action_lookup_falls_back_to_english_default()
    test_danger_tag_translation()
    print("all i18n tests OK")
