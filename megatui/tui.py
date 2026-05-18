"""curses TUI for MegaCli64.

Main loop runs ~30fps, redrawing on input or after a write action. Data is
fetched synchronously when the user presses 'r' (or on first launch). All
write actions go through a confirmation modal that previews the exact
MegaCli64 command and asks for either Y/N or a typed phrase for
catastrophic operations.
"""
from __future__ import annotations

import curses
import time
from dataclasses import dataclass, field
from typing import Any

from . import actions as A
from . import audit
from . import parsers as P
from .backends import Backend, MegaCliBackend, detect
from .i18n import t


TAB_KEYS = (
    "ui.tab.physical_drives",
    "ui.tab.logical_drives",
    "ui.tab.adapter_bbu",
    "ui.tab.enclosures",
)
TAB_DEFAULTS = ("Physical Drives", "Logical Drives", "Adapter+BBU", "Enclosures")


def tabs() -> tuple[str, ...]:
    """Localized tab labels."""
    return tuple(t(k, default=d) for k, d in zip(TAB_KEYS, TAB_DEFAULTS))


def action_title(a: A.Action) -> str:
    return t(f"action.{a.key}.title", default=a.title)


def action_summary(a: A.Action) -> str:
    return t(f"action.{a.key}.summary", default=a.summary)


def danger_tag(danger: str) -> str:
    defaults = {
        "safe":         " safe ",
        "write":        " write",
        "destructive":  "DANGER",
        "catastrophic": "DESTROY",
    }
    return t(f"ui.danger.{danger}", default=defaults.get(danger, "??"))


def _numeric_key(s: str) -> tuple[int, int | str]:
    """Sort key that orders numeric strings naturally with non-numerics last."""
    try:
        return (0, int(s))
    except (TypeError, ValueError):
        return (1, s or "")


@dataclass
class State:
    adapters: list[P.Adapter] = field(default_factory=list)
    pds: list[P.PhysicalDrive] = field(default_factory=list)
    lds: list[P.LogicalDrive] = field(default_factory=list)
    encs: list[P.Enclosure] = field(default_factory=list)
    bbu: list[P.BBUStatus] = field(default_factory=list)
    selected_adapter: int = 0
    tab: int = 0
    cursor: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 0, 2: 0, 3: 0})
    status: str = ""
    status_kind: str = "info"  # "info" | "ok" | "warn" | "err"
    last_refresh: float = 0.0


# --------------------------------------------------------------------------- #
# Color setup
# --------------------------------------------------------------------------- #

COLOR_DEFAULT = 0
COLOR_HEADER = 1
COLOR_TAB_ACTIVE = 2
COLOR_TAB_INACTIVE = 3
COLOR_OK = 4
COLOR_WARN = 5
COLOR_ERR = 6
COLOR_INFO = 7
COLOR_HILITE = 8
COLOR_DIM = 9
COLOR_DANGER = 10


def init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    curses.init_pair(COLOR_HEADER, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(COLOR_TAB_ACTIVE, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(COLOR_TAB_INACTIVE, curses.COLOR_WHITE, bg)
    curses.init_pair(COLOR_OK, curses.COLOR_GREEN, bg)
    curses.init_pair(COLOR_WARN, curses.COLOR_YELLOW, bg)
    curses.init_pair(COLOR_ERR, curses.COLOR_RED, bg)
    curses.init_pair(COLOR_INFO, curses.COLOR_CYAN, bg)
    curses.init_pair(COLOR_HILITE, curses.COLOR_BLACK, curses.COLOR_YELLOW)
    curses.init_pair(COLOR_DIM, curses.COLOR_WHITE, bg)
    curses.init_pair(COLOR_DANGER, curses.COLOR_WHITE, curses.COLOR_RED)


def state_color(state: str) -> int:
    s = state.lower()
    if not s:
        return curses.color_pair(COLOR_DIM)
    if "online" in s or "optimal" in s:
        return curses.color_pair(COLOR_OK) | curses.A_BOLD
    if "rebuild" in s or "copyback" in s or "degraded" in s or "init" in s:
        return curses.color_pair(COLOR_WARN) | curses.A_BOLD
    if "fail" in s or "bad" in s or "offline" in s or "missing" in s:
        return curses.color_pair(COLOR_ERR) | curses.A_BOLD
    if "hotspare" in s or "spare" in s:
        return curses.color_pair(COLOR_INFO) | curses.A_BOLD
    if "foreign" in s or "unconfigured" in s:
        return curses.color_pair(COLOR_INFO)
    return curses.color_pair(COLOR_DIM)


def state_glyph(state: str) -> str:
    s = state.lower()
    if "online" in s or "optimal" in s:
        return "●"
    if "rebuild" in s or "copyback" in s or "init" in s:
        return "◐"
    if "degraded" in s:
        return "◑"
    if "fail" in s or "bad" in s or "offline" in s:
        return "✗"
    if "missing" in s:
        return "?"
    if "hotspare" in s or "spare" in s:
        return "★"
    if "foreign" in s:
        return "↯"
    if "unconfigured" in s:
        return "○"
    return "·"


# --------------------------------------------------------------------------- #
# Drawing helpers
# --------------------------------------------------------------------------- #


def safe_addnstr(win: Any, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
    """addnstr that swallows boundary errors (writing the bottom-right cell)."""
    try:
        win.addnstr(y, x, text, n, attr)
    except curses.error:
        pass


def hline(win: Any, y: int, x: int, n: int, attr: int = 0) -> None:
    try:
        win.hline(y, x, curses.ACS_HLINE, n, attr)
    except curses.error:
        pass


def draw_tabs(win: Any, state: State, width: int) -> None:
    safe_addnstr(win, 0, 0, " " * width, width, curses.color_pair(COLOR_HEADER))
    label = f" MegaTUI · adapter {state.selected_adapter} "
    safe_addnstr(win, 0, 0, label, width, curses.color_pair(COLOR_HEADER) | curses.A_BOLD)
    x = len(label) + 2
    for idx, name in enumerate(tabs()):
        is_active = idx == state.tab
        text = f" F{idx+1} {name} "
        attr = curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD if is_active else curses.color_pair(COLOR_TAB_INACTIVE)
        safe_addnstr(win, 0, x, text, max(0, width - x), attr)
        x += len(text) + 1
        if x >= width:
            break


def draw_status(win: Any, state: State, height: int, width: int) -> None:
    bar_y = height - 2
    hline(win, bar_y, 0, width, curses.color_pair(COLOR_DIM))
    msg = state.status
    if state.status_kind == "err":
        attr = curses.color_pair(COLOR_ERR) | curses.A_BOLD
    elif state.status_kind == "ok":
        attr = curses.color_pair(COLOR_OK) | curses.A_BOLD
    elif state.status_kind == "warn":
        attr = curses.color_pair(COLOR_WARN) | curses.A_BOLD
    else:
        attr = curses.color_pair(COLOR_INFO)
    safe_addnstr(win, bar_y, 1, msg[:width - 2], width - 2, attr)
    helpline = t(
        "ui.footer.full",
        default=" ↑↓ select   Tab/Shift-Tab tab   F1-F4 jump   Enter detail   "
                "a action   r refresh   q quit",
    )
    safe_addnstr(win, height - 1, 0, helpline.ljust(width)[:width], width,
                 curses.color_pair(COLOR_DIM) | curses.A_REVERSE)


# --------------------------------------------------------------------------- #
# Tab renderers
# --------------------------------------------------------------------------- #


def _trunc(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    if n <= 1:
        return s[:n]
    return s[: n - 1] + "…"


def render_pd_table(win: Any, state: State, top: int, height: int, width: int) -> None:
    cols = (
        (t("ui.col.slot",       default="Slot"),     5),
        (t("ui.col.enc",        default="Enc"),      5),
        (t("ui.col.devid",      default="DevId"),    6),
        (t("ui.col.size",       default="Size"),     11),
        (t("ui.col.state",      default="State"),    24),
        (t("ui.col.media_err",  default="MediaErr"), 9),
        (t("ui.col.other_err",  default="OtherErr"), 9),
        (t("ui.col.temp",       default="Temp"),     6),
        (t("ui.col.type",       default="Type"),     8),
        (t("ui.col.inquiry",    default="Inquiry"),
         max(8, width - (5 + 5 + 6 + 11 + 24 + 9 + 9 + 6 + 8 + 10))),
    )
    header_y = top
    x = 1
    safe_addnstr(win, header_y, 0, " " * width, width,
                 curses.color_pair(COLOR_TAB_ACTIVE))
    for name, w in cols:
        safe_addnstr(win, header_y, x, _trunc(name, w).ljust(w), w,
                     curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD)
        x += w + 1

    pds = [pd for pd in state.pds if pd.adapter == state.selected_adapter]
    if not pds:
        safe_addnstr(
            win, top + 2, 2,
            t("ui.empty.pds",
              default="No physical drives reported on this adapter."),
            width - 4, curses.color_pair(COLOR_DIM),
        )
        return

    cursor = state.cursor[0] % max(1, len(pds))
    state.cursor[0] = cursor
    visible = height - top - 1
    first = max(0, cursor - visible // 2)
    first = min(first, max(0, len(pds) - visible))

    for i, pd in enumerate(pds[first : first + visible]):
        idx = first + i
        y = top + 1 + i
        is_sel = idx == cursor
        base = curses.color_pair(COLOR_HILITE) if is_sel else 0
        try:
            win.move(y, 0)
            win.clrtoeol()
        except curses.error:
            pass
        if is_sel:
            safe_addnstr(win, y, 0, " " * width, width, base)
        glyph = state_glyph(pd.state)
        state_str = f"{glyph} {pd.state}" if pd.state else "—"
        size = pd.size.replace(" [", "  [")
        size_short = size.split("[")[0].strip() or "—"
        media_type = pd.media_type or pd.pd_type or ""
        type_short = "SSD" if "Solid" in media_type else "HDD" if "Hard" in media_type else (pd.pd_type[:8] or "—")
        if "Tape" in pd.pd_type:
            type_short = "Tape"
        row = (
            (pd.slot or "—", 5),
            (pd.enclosure or "—", 5),
            (pd.device_id or "—", 6),
            (_trunc(size_short, 11), 11),
            (_trunc(state_str, 24), 24),
            (_trunc(pd.media_errors or "0", 9), 9),
            (_trunc(pd.other_errors or "0", 9), 9),
            (_trunc(pd.temperature.split(" ")[0] if pd.temperature else "—", 6), 6),
            (_trunc(type_short, 8), 8),
            (_trunc(pd.inquiry, cols[-1][1]), cols[-1][1]),
        )
        x = 1
        for ci, (value, w) in enumerate(row):
            attr = base
            if ci == 4:  # State column
                attr = (state_color(pd.state) | (curses.A_REVERSE if is_sel else 0))
            elif ci == 5 and (pd.media_errors or "0") not in ("", "0"):
                attr = curses.color_pair(COLOR_ERR) | curses.A_BOLD | (curses.A_REVERSE if is_sel else 0)
            elif ci == 7 and pd.temperature:
                temp_val = "".join(ch for ch in pd.temperature if ch.isdigit())
                if temp_val:
                    temp_c = int(temp_val[:2]) if len(temp_val) >= 2 else 0
                    if temp_c >= 60:
                        attr = curses.color_pair(COLOR_ERR) | curses.A_BOLD | (curses.A_REVERSE if is_sel else 0)
                    elif temp_c >= 50:
                        attr = curses.color_pair(COLOR_WARN) | (curses.A_REVERSE if is_sel else 0)
            safe_addnstr(win, y, x, value.ljust(w), w, attr or base)
            x += w + 1


def render_ld_table(win: Any, state: State, top: int, height: int, width: int) -> None:
    cols = (
        (t("ui.col.ld",     default="LD"),     4),
        (t("ui.col.name",   default="Name"),   14),
        (t("ui.col.raid",   default="RAID"),   26),
        (t("ui.col.size",   default="Size"),   12),
        (t("ui.col.drives", default="Drives"), 7),
        (t("ui.col.state",  default="State"),  12),
        (t("ui.col.strip",  default="Strip"),  8),
        (t("ui.col.cache",  default="Cache"),
         max(8, width - (4 + 14 + 26 + 12 + 7 + 12 + 8 + 8))),
    )
    header_y = top
    x = 1
    safe_addnstr(win, header_y, 0, " " * width, width,
                 curses.color_pair(COLOR_TAB_ACTIVE))
    for name, w in cols:
        safe_addnstr(win, header_y, x, _trunc(name, w).ljust(w), w,
                     curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD)
        x += w + 1

    lds = [ld for ld in state.lds if ld.adapter == state.selected_adapter]
    if not lds:
        safe_addnstr(
            win, top + 2, 2,
            t("ui.empty.lds",
              default="No virtual drives configured. Use external tools to create RAID volumes."),
            width - 4, curses.color_pair(COLOR_DIM),
        )
        return

    cursor = state.cursor[1] % max(1, len(lds))
    state.cursor[1] = cursor
    visible = height - top - 1
    first = max(0, cursor - visible // 2)
    first = min(first, max(0, len(lds) - visible))

    for i, ld in enumerate(lds[first : first + visible]):
        idx = first + i
        y = top + 1 + i
        is_sel = idx == cursor
        base = curses.color_pair(COLOR_HILITE) if is_sel else 0
        try:
            win.move(y, 0)
            win.clrtoeol()
        except curses.error:
            pass
        if is_sel:
            safe_addnstr(win, y, 0, " " * width, width, base)
        glyph = state_glyph(ld.state)
        state_str = f"{glyph} {ld.state}" if ld.state else "—"
        cache = ld.write_cache.split(",")[0] if ld.write_cache else "—"
        row = (
            (ld.ld_index or "—", 4),
            (_trunc(ld.name or "—", 14), 14),
            (_trunc(ld.raid_level, 26), 26),
            (_trunc(ld.size, 12), 12),
            (_trunc(ld.num_drives or "—", 7), 7),
            (_trunc(state_str, 12), 12),
            (_trunc(ld.strip_size, 8), 8),
            (_trunc(cache, cols[-1][1]), cols[-1][1]),
        )
        x = 1
        for ci, (value, w) in enumerate(row):
            attr = base
            if ci == 5:
                attr = state_color(ld.state) | (curses.A_REVERSE if is_sel else 0)
            safe_addnstr(win, y, x, value.ljust(w), w, attr or base)
            x += w + 1


def _two_col_lines(pairs: list[tuple[str, str]], col_width: int) -> list[tuple[str, str, str]]:
    return [(label, value, "") for label, value in pairs]


def render_adapter_bbu(win: Any, state: State, top: int, height: int, width: int) -> None:
    adps = [a for a in state.adapters if a.index == state.selected_adapter]
    if not adps:
        safe_addnstr(win, top + 1, 2,
                     t("ui.empty.adp",
                       default="No adapter info loaded. Press [r] to refresh."),
                     width - 4, curses.color_pair(COLOR_DIM))
        return
    a = adps[0]
    bbu_list = [b for b in state.bbu if b.adapter == state.selected_adapter]
    bbu = bbu_list[0] if bbu_list else None

    pairs_left: list[tuple[str, str, int]] = [
        (t("ui.adp.product",          default="Product"),          a.product, COLOR_INFO),
        (t("ui.adp.serial",           default="Serial"),           a.serial, 0),
        (t("ui.adp.fw_version",       default="FW Version"),       a.get("FW Version") or a.fw, 0),
        (t("ui.adp.fw_package",       default="FW Package"),       a.get("FW Package Build"), 0),
        (t("ui.adp.bios",             default="BIOS"),             a.get("BIOS Version"), 0),
        (t("ui.adp.memory",           default="Memory"),           a.memory, 0),
        (t("ui.adp.sas_address",      default="SAS Address"),      a.get("SAS Address"), 0),
        (t("ui.adp.host_interface",   default="Host Interface"),   a.get("Host Interface"), 0),
        (t("ui.adp.backend_ports",    default="Backend Ports"),    a.get("Number of Backend Port"), 0),
        (t("ui.adp.virtual_drives",   default="Virtual Drives"),   a.virtual_drives, 0),
        (t("ui.adp.physical_devices", default="Physical Devices"), a.physical_devices, 0),
        (t("ui.adp.disks_failed",     default="Disks (Failed)"),
         f"{a.get('Disks')} ({a.get('Failed Disks')} failed)", 0),
        (t("ui.adp.rebuild_rate",     default="Rebuild Rate"),     a.get("Rebuild Rate"), 0),
        (t("ui.adp.pr_rate",          default="Patrol Read Rate"), a.get("PR Rate"), 0),
        (t("ui.adp.bgi_rate",         default="BGI Rate"),         a.get("BGI Rate"), 0),
        (t("ui.adp.cc_rate",          default="CC Rate"),          a.get("Check Consistency Rate"), 0),
        (t("ui.adp.auto_rebuild",     default="Auto Rebuild"),     a.get("Auto Rebuild"), 0),
        (t("ui.adp.alarm",            default="Alarm"),            a.get("Alarm"), 0),
    ]

    safe_addnstr(win, top, 2, t("ui.section.adapter", default="Adapter"), width - 4,
                 curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD)

    col_w = max(20, width // 2 - 2)
    y = top + 2
    for label, value, color in pairs_left:
        if y >= height - 3:
            break
        attr = curses.color_pair(color) | curses.A_BOLD if color else curses.A_BOLD
        safe_addnstr(win, y, 2, f"{label:<18}", 18, attr)
        safe_addnstr(win, y, 22, _trunc(value or "—", col_w - 22), col_w - 22, 0)
        y += 1

    # BBU panel on the right half
    rx = col_w + 2
    safe_addnstr(win, top, rx, t("ui.section.bbu", default="BBU"), width - rx - 1,
                 curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD)
    y = top + 2
    if bbu is None:
        safe_addnstr(win, y, rx,
                     t("ui.empty.bbu_unloaded",
                       default="Not queried yet — press [r] to refresh."),
                     width - rx - 1, curses.color_pair(COLOR_DIM))
        return
    if not bbu.present:
        safe_addnstr(win, y, rx, t("ui.bbu.status", default="Status:"), 8, curses.A_BOLD)
        safe_addnstr(win, y, rx + 10,
                     t("ui.empty.bbu_absent", default="Absent / Unsupported"),
                     width - rx - 11, curses.color_pair(COLOR_ERR) | curses.A_BOLD)
        y += 1
        if bbu.error:
            safe_addnstr(win, y, rx, _trunc(bbu.error, width - rx - 1),
                         width - rx - 1, curses.color_pair(COLOR_DIM))
        return

    # (key, default_label, value) — key is used for type-specific coloring so
    # comparisons stay stable across languages.
    bbu_pairs = [
        ("state",          "State",          bbu.state),
        ("battery_type",   "Battery Type",   bbu.battery_type),
        ("charge",         "Charge",         bbu.charge),
        ("voltage",        "Voltage",        bbu.voltage),
        ("current",        "Current",        bbu.current),
        ("temperature",    "Temperature",    bbu.temperature),
        ("charger_status", "Charger Status", bbu.raw.get("Charger Status", "")),
        ("remaining",      "Remaining",      bbu.raw.get("Remaining Capacity", "")),
        ("full_capacity",  "Full Capacity",  bbu.raw.get("Full Charge Capacity", "")),
        ("replacement",    "Replacement",    bbu.raw.get("Battery Replacement required", "")),
        ("learn_active",   "Learn Active",   bbu.raw.get("Learn Cycle Active", "")),
        ("learn_status",   "Learn Status",   bbu.raw.get("Learn Cycle Status", "")),
    ]
    for key, default_label, value in bbu_pairs:
        if y >= height - 3:
            break
        label = t(f"ui.bbu.{key}", default=default_label)
        attr = curses.A_BOLD
        safe_addnstr(win, y, rx, f"{label:<16}", 16, attr)
        v = value or "—"
        v_attr = 0
        if key == "state" and value:
            v_attr = state_color(value)
        if key == "replacement" and value and value.lower() not in ("no", "false"):
            v_attr = curses.color_pair(COLOR_ERR) | curses.A_BOLD
        safe_addnstr(win, y, rx + 18, _trunc(v, width - rx - 19),
                     width - rx - 19, v_attr)
        y += 1


def render_enclosures(win: Any, state: State, top: int, height: int, width: int) -> None:
    cols = (
        (t("ui.col.adp",            default="Adp"),            4),
        (t("ui.col.enc_hash",       default="Enc#"),           5),
        (t("ui.col.devid_full",     default="DevID"),          6),
        (t("ui.col.slots",          default="Slots"),          6),
        (t("ui.col.pds",            default="PDs"),            4),
        (t("ui.col.psu",            default="PSU"),            4),
        (t("ui.col.fan",            default="Fan"),            4),
        (t("ui.col.tempsensors",    default="TempSensors"),    12),
        (t("ui.col.status",         default="Status"),         14),
        (t("ui.col.type",           default="Type"),           10),
        (t("ui.col.vendor_product", default="Vendor/Product"),
         max(8, width - (4 + 5 + 6 + 6 + 4 + 4 + 4 + 12 + 14 + 10 + 11))),
    )
    header_y = top
    x = 1
    safe_addnstr(win, header_y, 0, " " * width, width,
                 curses.color_pair(COLOR_TAB_ACTIVE))
    for name, w in cols:
        safe_addnstr(win, header_y, x, _trunc(name, w).ljust(w), w,
                     curses.color_pair(COLOR_TAB_ACTIVE) | curses.A_BOLD)
        x += w + 1

    encs = [e for e in state.encs if e.adapter == state.selected_adapter]
    if not encs:
        safe_addnstr(win, top + 2, 2,
                     t("ui.empty.encs", default="No enclosures reported."),
                     width - 4, curses.color_pair(COLOR_DIM))
        return
    cursor = state.cursor[3] % max(1, len(encs))
    state.cursor[3] = cursor
    visible = height - top - 1
    first = max(0, cursor - visible // 2)
    first = min(first, max(0, len(encs) - visible))
    for i, e in enumerate(encs[first : first + visible]):
        idx = first + i
        y = top + 1 + i
        is_sel = idx == cursor
        base = curses.color_pair(COLOR_HILITE) if is_sel else 0
        try:
            win.move(y, 0)
            win.clrtoeol()
        except curses.error:
            pass
        if is_sel:
            safe_addnstr(win, y, 0, " " * width, width, base)
        vendor = e.raw.get("Vendor Identification", "").strip()
        product = e.raw.get("Product Identification", "").strip()
        vp = f"{vendor} {product}".strip() or "—"
        row = (
            (str(e.adapter), 4),
            (e.index, 5),
            (e.device_id, 6),
            (e.slots, 6),
            (e.num_drives, 4),
            (e.raw.get("Number of Power Supplies", "0"), 4),
            (e.raw.get("Number of Fans", "0"), 4),
            (e.raw.get("Number of Temperature Sensors", "0"), 12),
            (_trunc(e.status, 14), 14),
            (_trunc(e.enc_type, 10), 10),
            (_trunc(vp, cols[-1][1]), cols[-1][1]),
        )
        x = 1
        for ci, (value, w) in enumerate(row):
            attr = base
            if ci == 8:
                attr = state_color(e.status) | (curses.A_REVERSE if is_sel else 0)
            safe_addnstr(win, y, x, str(value).ljust(w), w, attr or base)
            x += w + 1


# --------------------------------------------------------------------------- #
# Modals
# --------------------------------------------------------------------------- #


def _centered_panel(stdscr: Any, h: int, w: int) -> Any:
    H, W = stdscr.getmaxyx()
    h = min(h, H - 2)
    w = min(w, W - 2)
    y = max(0, (H - h) // 2)
    x = max(0, (W - w) // 2)
    win = curses.newwin(h, w, y, x)
    win.keypad(True)
    return win


def _draw_box(win: Any, title: str, color: int = COLOR_INFO) -> None:
    win.erase()
    win.attron(curses.color_pair(color) | curses.A_BOLD)
    win.box()
    win.attroff(curses.color_pair(color) | curses.A_BOLD)
    win.addstr(0, 2, f" {title} ", curses.color_pair(color) | curses.A_BOLD)


def detail_modal(stdscr: Any, title: str, kv: list[tuple[str, str]]) -> None:
    H, W = stdscr.getmaxyx()
    longest_key = max((len(k) for k, _ in kv), default=0)
    longest_val = max((len(str(v)) for _, v in kv), default=0)
    title_w = len(title) + 6
    # Layout: 2 left margin | key | 2 gap | value | 2 right margin
    ideal_width = 2 + longest_key + 2 + longest_val + 2
    width = max(50, title_w, min(ideal_width, W - 2))
    height = min(len(kv) + 4, H - 2)
    win = _centered_panel(stdscr, height, width)
    _draw_box(win, title)
    # Cap the key column only when the terminal is too narrow to fit it
    # alongside a usable value column. Otherwise keep keys full-length.
    key_col_w = min(longest_key, max(8, width - 8))
    val_col_x = 2 + key_col_w + 2
    val_col_w = max(1, width - val_col_x - 2)
    for i, (k, v) in enumerate(kv[: height - 4]):
        safe_addnstr(win, 2 + i, 2, k, key_col_w, curses.A_BOLD)
        safe_addnstr(win, 2 + i, val_col_x, str(v), val_col_w)
    safe_addnstr(win, height - 2, 2,
                 t("ui.modal.close_hint", default="[Esc/q] close"),
                 width - 4, curses.color_pair(COLOR_DIM))
    win.refresh()
    while True:
        ch = win.getch()
        if ch in (27, ord("q"), ord("Q"), curses.KEY_ENTER, 10, 13):
            return


def message_modal(stdscr: Any, title: str, lines: list[str], color: int = COLOR_INFO) -> None:
    height = min(len(lines) + 4, stdscr.getmaxyx()[0] - 2)
    width = min(max(50, max((len(s) for s in lines), default=50) + 4),
                stdscr.getmaxyx()[1] - 2)
    win = _centered_panel(stdscr, height, width)
    _draw_box(win, title, color)
    for i, line in enumerate(lines[: height - 4]):
        try:
            win.addnstr(2 + i, 2, line, width - 4)
        except curses.error:
            pass
    win.addstr(height - 2, 2,
               t("ui.modal.enter_close_hint", default="[Enter/Esc] close"),
               curses.color_pair(COLOR_DIM))
    win.refresh()
    while True:
        ch = win.getch()
        if ch in (27, ord("q"), ord("Q"), curses.KEY_ENTER, 10, 13):
            return


def _danger_color(d: str) -> int:
    return {
        "safe": COLOR_OK,
        "write": COLOR_WARN,
        "destructive": COLOR_ERR,
        "catastrophic": COLOR_DANGER,
    }.get(d, COLOR_INFO)


def action_picker(stdscr: Any, title: str, opts: list[A.Action]) -> A.Action | None:
    if not opts:
        message_modal(
            stdscr,
            t("ui.picker.no_actions_title", default="No actions"),
            [t("ui.picker.no_actions_body",
               default="No actions available for this target.")],
            COLOR_DIM,
        )
        return None
    titles = [action_title(o) for o in opts]
    summaries = [action_summary(o) for o in opts]
    height = min(len(opts) + 5, stdscr.getmaxyx()[0] - 2)
    width = min(max(60, max(len(tt) + len(ss) + 8 for tt, ss in zip(titles, summaries))),
                stdscr.getmaxyx()[1] - 2)
    win = _centered_panel(stdscr, height, width)
    cur = 0
    while True:
        _draw_box(win, title)
        for i, opt in enumerate(opts[: height - 5]):
            tag = danger_tag(opt.danger)
            tag_attr = curses.color_pair(_danger_color(opt.danger)) | curses.A_BOLD
            line_attr = curses.A_REVERSE if i == cur else 0
            try:
                win.addnstr(2 + i, 2, " " * (width - 4), width - 4, line_attr)
                win.addstr(2 + i, 2, f" [{tag}] ", tag_attr | line_attr)
                win.addnstr(2 + i, 12, titles[i].ljust(28), 28, line_attr | curses.A_BOLD)
                win.addnstr(2 + i, 42, summaries[i], max(0, width - 44), line_attr)
            except curses.error:
                pass
        win.addstr(height - 2, 2,
                   t("ui.picker.hint",
                     default="[↑↓] move  [Enter] select  [Esc] cancel"),
                   curses.color_pair(COLOR_DIM))
        win.refresh()
        ch = win.getch()
        if ch in (27, ord("q"), ord("Q")):
            return None
        if ch in (curses.KEY_UP, ord("k")):
            cur = (cur - 1) % len(opts)
        elif ch in (curses.KEY_DOWN, ord("j")):
            cur = (cur + 1) % len(opts)
        elif ch in (curses.KEY_ENTER, 10, 13):
            return opts[cur]


def confirm_action(stdscr: Any, action: A.Action, argv_preview: list[str],
                   target_label: str) -> bool:
    """Confirmation dialog. Catastrophic actions require typed phrase."""
    cmd_str = " ".join(argv_preview)
    title_txt = action_title(action)
    summary_txt = action_summary(action)
    danger_label = t(f"ui.danger.{action.danger}_full",
                     default=action.danger.upper())
    # Per-line tags so layout/coloring stays language-independent.
    lines: list[tuple[str, str]] = [
        ("action", f"{t('ui.confirm.action', default='Action:')} {title_txt}"),
        ("target", f"{t('ui.confirm.target', default='Target:')} {target_label}"),
        ("danger", f"{t('ui.confirm.danger', default='Danger:')} {danger_label}"),
        ("blank",  ""),
        ("summary", summary_txt),
        ("blank",  ""),
        ("cmd_h",  t("ui.confirm.command", default="Command:")),
        ("cmd",    f"  {cmd_str}"),
        ("blank",  ""),
    ]
    if action.danger == "catastrophic":
        lines.append((
            "typed",
            t("ui.confirm.typed_phrase",
              default=f"Type exactly: {action.confirm_phrase!r} to confirm",
              phrase=action.confirm_phrase),
        ))
    else:
        lines.append((
            "yn",
            t("ui.confirm.yes_no_hint",
              default="[y/Enter] confirm   [n/Esc] cancel"),
        ))

    height = min(len(lines) + 5, stdscr.getmaxyx()[0] - 2)
    width = min(max(70, max(len(line) for _, line in lines) + 6), stdscr.getmaxyx()[1] - 2)
    win = _centered_panel(stdscr, height, width)
    color = _danger_color(action.danger)
    _draw_box(win, t("ui.confirm.title", default="Confirm: {title}", title=title_txt), color)
    for i, (tag, line) in enumerate(lines[: height - 5]):
        attr = 0
        if tag == "danger":
            attr = curses.color_pair(color) | curses.A_BOLD
        elif tag == "cmd":
            attr = curses.color_pair(COLOR_INFO)
        elif tag == "typed":
            attr = curses.color_pair(COLOR_DANGER) | curses.A_BOLD
        try:
            win.addnstr(2 + i, 2, line, width - 4, attr)
        except curses.error:
            pass
    win.refresh()

    if action.danger != "catastrophic":
        while True:
            ch = win.getch()
            if ch in (ord("y"), ord("Y"), curses.KEY_ENTER, 10, 13):
                return True
            if ch in (ord("n"), ord("N"), 27, ord("q"), ord("Q")):
                return False

    # typed-phrase confirmation
    prompt_y = height - 3
    win.addstr(prompt_y, 2, t("ui.confirm.prompt", default="Confirm > "),
               curses.color_pair(COLOR_DANGER) | curses.A_BOLD)
    curses.echo()
    curses.curs_set(1)
    try:
        try:
            entered = win.getstr(prompt_y, 12, max(8, len(action.confirm_phrase) + 8))
        except curses.error:
            entered = b""
    finally:
        curses.noecho()
        curses.curs_set(0)
    typed = entered.decode("utf-8", errors="replace").strip()
    return typed == action.confirm_phrase


# --------------------------------------------------------------------------- #
# App
# --------------------------------------------------------------------------- #


class App:
    def __init__(self, backend: Backend, fixture_mode: bool = False) -> None:
        self.backend = backend
        self.state = State()
        self.fixture_mode = fixture_mode

    # -- data -----------------------------------------------------------------

    def refresh(self) -> None:
        self.state.status = t("ui.status.refreshing", default="Refreshing…")
        self.state.status_kind = "info"
        try:
            self.state.adapters = self.backend.adapters()

            pds = self.backend.physical_drives()
            pds.sort(key=lambda p: (p.adapter, _numeric_key(p.device_id)))
            self.state.pds = pds

            lds = self.backend.logical_drives()
            lds.sort(key=lambda d: (d.adapter, _numeric_key(d.ld_index)))
            self.state.lds = lds

            encs = self.backend.enclosures()
            encs.sort(key=lambda e: (e.adapter, _numeric_key(e.device_id)))
            self.state.encs = encs

            self.state.bbu = self.backend.bbu_statuses()

            self.state.last_refresh = time.time()
            self.state.status = t(
                "ui.status.refreshed",
                default="[{backend}] Refreshed {time}  adapters={adapters} "
                        "PDs={pds} LDs={lds} Encs={encs}",
                backend=self.backend.name,
                time=time.strftime("%H:%M:%S"),
                adapters=len(self.state.adapters),
                pds=len(self.state.pds),
                lds=len(self.state.lds),
                encs=len(self.state.encs),
            )
            self.state.status_kind = "ok"
        except Exception as exc:  # noqa: BLE001
            self.state.status = t(
                "ui.status.refresh_failed",
                default="Refresh failed: {exc}",
                exc=exc,
            )
            self.state.status_kind = "err"

    # -- selection -----------------------------------------------------------

    def _current_pd(self) -> P.PhysicalDrive | None:
        pds = [pd for pd in self.state.pds if pd.adapter == self.state.selected_adapter]
        if not pds:
            return None
        return pds[self.state.cursor[0] % len(pds)]

    def _current_ld(self) -> P.LogicalDrive | None:
        lds = [ld for ld in self.state.lds if ld.adapter == self.state.selected_adapter]
        if not lds:
            return None
        return lds[self.state.cursor[1] % len(lds)]

    def _current_enc(self) -> P.Enclosure | None:
        encs = [e for e in self.state.encs if e.adapter == self.state.selected_adapter]
        if not encs:
            return None
        return encs[self.state.cursor[3] % len(encs)]

    # -- detail / actions ----------------------------------------------------

    def show_detail(self, stdscr: Any) -> None:
        tab = self.state.tab
        if tab == 0:
            pd = self._current_pd()
            if pd is None:
                return
            kv = list(pd.raw.items())
            detail_modal(stdscr,
                         t("ui.modal.pd_title", default="PD slot={slot} dev={dev}",
                           slot=pd.slot, dev=pd.device_id),
                         kv)
        elif tab == 1:
            ld = self._current_ld()
            if ld is None:
                return
            kv = list(ld.raw.items())
            detail_modal(stdscr,
                         t("ui.modal.ld_title", default="LD {idx} ({name})",
                           idx=ld.ld_index, name=ld.name),
                         kv)
        elif tab == 2:
            adps = [a for a in self.state.adapters if a.index == self.state.selected_adapter]
            if not adps:
                return
            a = adps[0]
            kv = list(a.flat.items())
            detail_modal(stdscr,
                         t("ui.modal.adp_title", default="Adapter {idx}", idx=a.index),
                         kv)
        else:
            e = self._current_enc()
            if e is None:
                return
            detail_modal(stdscr,
                         t("ui.modal.enc_title", default="Enclosure {idx}", idx=e.index),
                         list(e.raw.items()))

    def run_action(self, stdscr: Any) -> None:
        tab = self.state.tab
        target_kind: str
        target_label: str
        target: Any
        if tab == 0:
            target = self._current_pd()
            if target is None:
                return
            target_kind = "pd"
            target_label = (
                f"PD slot={target.slot or '-'} enc={target.enclosure or '-'} "
                f"dev={target.device_id} state={target.state or '-'}"
            )
        elif tab == 1:
            target = self._current_ld()
            if target is None:
                return
            target_kind = "ld"
            target_label = f"LD {target.ld_index} ({target.name}) {target.raid_level}"
        else:
            target_kind = "adapter"
            target_label = f"Adapter {self.state.selected_adapter}"
            target = self.state.selected_adapter

        opts = A.applicable_actions(target_kind, target, backend=self.backend)
        action = action_picker(
            stdscr,
            t("ui.picker.title", default="Action — {target}", target=target_label),
            opts,
        )
        if action is None:
            return

        title_txt = action_title(action)
        argv_args = self.backend.build_argv(action.key, target)
        argv_preview = self.backend.preview_argv(list(argv_args))
        if not confirm_action(stdscr, action, argv_preview, target_label):
            self.state.status = t("ui.status.cancelled", default="Cancelled.")
            self.state.status_kind = "warn"
            return

        if self.fixture_mode:
            audit.log(f"DRYRUN:{action.key}", argv_preview, 0,
                      f"target={target_label}")
            self.state.status = t(
                "ui.status.fixture_dry_run",
                default="[fixture mode] would run: {cmd}",
                cmd=self.backend.shell_repr(tuple(argv_preview)),
            )
            self.state.status_kind = "warn"
            message_modal(
                stdscr,
                t("ui.modal.fixture_title", default="Fixture mode (dry run)"),
                [
                    t("ui.modal.fixture_line1",
                      default="No command was executed."),
                    t("ui.modal.fixture_line2",
                      default="Unset MEGATUI_FIXTURES to run for real."),
                    "",
                    f"  {self.backend.shell_repr(tuple(argv_preview))}",
                ],
                COLOR_INFO,
            )
            return

        result = self.backend.run(list(argv_args))
        audit.log(action.key, list(result.argv), result.rc,
                  f"target={target_label} | " + (result.stdout or result.stderr))
        no_output = t("ui.modal.no_output", default="(no output)")
        out_lines = (result.stdout or result.stderr or no_output).splitlines()
        if result.ok:
            self.state.status = t("ui.status.ok", default="OK: {title}", title=title_txt)
            self.state.status_kind = "ok"
            message_modal(stdscr,
                          t("ui.modal.ok_title", default="OK — {title}", title=title_txt),
                          out_lines[:30] or [no_output], COLOR_OK)
        else:
            self.state.status = t("ui.status.fail", default="FAIL ({rc}): {title}",
                                  rc=result.rc, title=title_txt)
            self.state.status_kind = "err"
            message_modal(stdscr,
                          t("ui.modal.fail_title", default="FAIL ({rc}) — {title}",
                            rc=result.rc, title=title_txt),
                          out_lines[:30] or [no_output], COLOR_ERR)
        # Refresh for visible side effects.
        self.refresh()

    # -- main loop -----------------------------------------------------------

    def loop(self, stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.nodelay(False)
        stdscr.keypad(True)
        init_colors()

        self.refresh()

        while True:
            try:
                stdscr.erase()
                H, W = stdscr.getmaxyx()
                if H < 12 or W < 80:
                    safe_addnstr(stdscr, 0, 0,
                                 t("ui.footer.term_small",
                                   default="Terminal too small ({w}x{h}) — needs 80x12 minimum.",
                                   w=W, h=H),
                                 W, curses.A_BOLD)
                    stdscr.refresh()
                    if stdscr.getch() in (ord("q"), 27):
                        return
                    continue
                draw_tabs(stdscr, self.state, W)
                top = 2
                body_h = H - 2
                if self.state.tab == 0:
                    render_pd_table(stdscr, self.state, top, body_h, W)
                elif self.state.tab == 1:
                    render_ld_table(stdscr, self.state, top, body_h, W)
                elif self.state.tab == 2:
                    render_adapter_bbu(stdscr, self.state, top, body_h, W)
                else:
                    render_enclosures(stdscr, self.state, top, body_h, W)
                draw_status(stdscr, self.state, H, W)
                stdscr.refresh()
            except curses.error:
                pass

            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q")):
                return
            if ch == curses.KEY_F1 or ch == ord("1"):
                self.state.tab = 0
            elif ch == curses.KEY_F2 or ch == ord("2"):
                self.state.tab = 1
            elif ch == curses.KEY_F3 or ch == ord("3"):
                self.state.tab = 2
            elif ch == curses.KEY_F4 or ch == ord("4"):
                self.state.tab = 3
            elif ch == 9:  # Tab
                self.state.tab = (self.state.tab + 1) % len(TAB_KEYS)
            elif ch == 353:  # Shift-Tab on most terms
                self.state.tab = (self.state.tab - 1) % len(TAB_KEYS)
            elif ch in (curses.KEY_UP, ord("k")):
                self.state.cursor[self.state.tab] = max(0, self.state.cursor[self.state.tab] - 1)
            elif ch in (curses.KEY_DOWN, ord("j")):
                self.state.cursor[self.state.tab] += 1
            elif ch == curses.KEY_HOME:
                self.state.cursor[self.state.tab] = 0
            elif ch == curses.KEY_END:
                self.state.cursor[self.state.tab] = 10**6
            elif ch == curses.KEY_PPAGE:
                self.state.cursor[self.state.tab] = max(0, self.state.cursor[self.state.tab] - 10)
            elif ch == curses.KEY_NPAGE:
                self.state.cursor[self.state.tab] += 10
            elif ch in (ord("r"), ord("R")):
                self.refresh()
            elif ch in (curses.KEY_ENTER, 10, 13):
                self.show_detail(stdscr)
            elif ch in (ord("a"), ord("A")):
                self.run_action(stdscr)


def run(use_sudo: bool = True, fixture_mode: bool = False,
        backend_name: str = "auto", fixtures_dir: str | None = None) -> int:
    backend = detect(name=backend_name, use_sudo=use_sudo, fixtures_dir=fixtures_dir)
    app = App(backend, fixture_mode=fixture_mode)
    curses.wrapper(app.loop)
    return 0
