"""Write-side MegaCli operations.

Each Action is a recipe that, given a target (a parsed PhysicalDrive,
LogicalDrive, or adapter index), produces an argv list to feed Runner.run().

Danger ratings:
    safe          — no data loss possible (locate LED, status queries)
    write         — changes runtime config (rates, hot-spare role, policies)
    destructive   — likely loses redundancy or interrupts I/O (offline, abort init)
    catastrophic  — destroys data or whole config (cfg clear, ld delete, pd clear)

Catastrophic actions require typed confirmation matching `confirm_phrase`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from .parsers import LogicalDrive, PhysicalDrive


Danger = Literal["safe", "write", "destructive", "catastrophic"]
TargetKind = Literal["pd", "ld", "adapter"]


@dataclass(frozen=True)
class Action:
    key: str  # short identifier
    title: str  # display in menu
    danger: Danger
    target: TargetKind
    build: Callable[..., list[str]]
    summary: str = ""  # short help line in confirmation dialog
    confirm_phrase: str = ""  # if non-empty, user must type this verbatim
    applicable: Callable[..., bool] | None = None  # gate visibility by target state


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _physdrv(pd: PhysicalDrive) -> str:
    """Format the [E:S] argument MegaCli expects for a physical drive."""
    enc = pd.enclosure or "0"
    slot = pd.slot or pd.device_id or "0"
    return f"[{enc}:{slot}]"


# --------------------------------------------------------------------------- #
# PD actions
# --------------------------------------------------------------------------- #


def _build_locate_on(pd: PhysicalDrive) -> list[str]:
    return ["-PdLocate", "-start", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_locate_off(pd: PhysicalDrive) -> list[str]:
    return ["-PdLocate", "-stop", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_hsp_set(pd: PhysicalDrive) -> list[str]:
    return ["-PDHSP", "-Set", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_hsp_remove(pd: PhysicalDrive) -> list[str]:
    return ["-PDHSP", "-Rmv", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_online(pd: PhysicalDrive) -> list[str]:
    return ["-PDOnline", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_offline(pd: PhysicalDrive) -> list[str]:
    return ["-PDOffline", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_mark_missing(pd: PhysicalDrive) -> list[str]:
    return ["-PDMarkMissing", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_make_good(pd: PhysicalDrive) -> list[str]:
    return ["-PDMakeGood", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_make_bad(pd: PhysicalDrive) -> list[str]:
    return ["-PDMakeBad", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_rebuild_start(pd: PhysicalDrive) -> list[str]:
    return ["-PDRbld", "-Start", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_rebuild_stop(pd: PhysicalDrive) -> list[str]:
    return ["-PDRbld", "-Stop", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_rebuild_progress(pd: PhysicalDrive) -> list[str]:
    return ["-PDRbld", "-ShowProg", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_clear_start(pd: PhysicalDrive) -> list[str]:
    return ["-PDClear", "-Start", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_clear_progress(pd: PhysicalDrive) -> list[str]:
    return ["-PDClear", "-ShowProg", "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]


def _build_pd_create_r0(pd: PhysicalDrive) -> list[str]:
    return ["-CfgLdAdd", "-r0", _physdrv(pd), f"-a{pd.adapter}"]


# --------------------------------------------------------------------------- #
# PD state predicates — gate which actions a menu surfaces.
# --------------------------------------------------------------------------- #

def _pd_state_lc(pd: PhysicalDrive) -> str:
    return (pd.state or "").lower()


def _pd_has_foreign(pd: PhysicalDrive) -> bool:
    return (pd.foreign_state or "").strip().lower() not in {"", "none"}


def _pd_is_unconfigured_good(pd: PhysicalDrive) -> bool:
    s = _pd_state_lc(pd)
    if "unconfigured(good)" not in s and "unconfigured (good)" not in s:
        return False
    return not _pd_has_foreign(pd)


def _pd_is_unconfigured_bad(pd: PhysicalDrive) -> bool:
    s = _pd_state_lc(pd)
    return "unconfigured(bad)" in s or "unconfigured (bad)" in s


def _pd_is_online(pd: PhysicalDrive) -> bool:
    return "online" in _pd_state_lc(pd)


def _pd_is_offline(pd: PhysicalDrive) -> bool:
    return "offline" in _pd_state_lc(pd)


def _pd_is_failed(pd: PhysicalDrive) -> bool:
    return "failed" in _pd_state_lc(pd)


def _pd_is_rebuilding(pd: PhysicalDrive) -> bool:
    return "rebuild" in _pd_state_lc(pd)


def _pd_is_hotspare(pd: PhysicalDrive) -> bool:
    s = _pd_state_lc(pd)
    return "hotspare" in s or "hot spare" in s


def _pd_recoverable(pd: PhysicalDrive) -> bool:
    """Targets where 'Make Good' would do something useful."""
    return _pd_is_failed(pd) or _pd_is_unconfigured_bad(pd) or _pd_has_foreign(pd)


def _pd_rebuildable(pd: PhysicalDrive) -> bool:
    """Drives that can be re-introduced to an array via manual rebuild start."""
    return _pd_is_failed(pd) or _pd_is_offline(pd) or _pd_is_unconfigured_bad(pd)


def _pd_can_make_bad(pd: PhysicalDrive) -> bool:
    """Force-fail makes sense on healthy or pseudo-healthy drives only."""
    return _pd_is_online(pd) or _pd_is_unconfigured_good(pd) or _pd_is_hotspare(pd)


def _pd_clearable(pd: PhysicalDrive) -> bool:
    """PD Clear (full wipe) — gate to drives outside any VD."""
    return _pd_is_unconfigured_good(pd) or _pd_is_unconfigured_bad(pd)


PD_ACTIONS: list[Action] = [
    Action("locate_on", "Locate LED ON", "safe", "pd", _build_locate_on,
           "Blink the slot LED to physically locate the drive."),
    Action("locate_off", "Locate LED OFF", "safe", "pd", _build_locate_off,
           "Stop the locate LED."),
    Action("rebuild_progress", "Rebuild progress", "safe", "pd", _build_pd_rebuild_progress,
           "Show current rebuild percentage / ETA."),
    Action("hsp_set", "Set as Global Hot Spare", "write", "pd", _build_hsp_set,
           "Configure this drive as a global hot spare.",
           applicable=_pd_is_unconfigured_good),
    Action("hsp_remove", "Remove Hot Spare role", "write", "pd", _build_hsp_remove,
           "Demote this hot spare back to Unconfigured Good.",
           applicable=_pd_is_hotspare),
    Action("pd_online", "PD Online", "write", "pd", _build_pd_online,
           "Force the drive online (use only if firmware state allows).",
           applicable=_pd_is_offline),
    Action("pd_make_good", "PD Make Good", "write", "pd", _build_pd_make_good,
           "Mark a foreign / failed drive as Unconfigured Good.",
           applicable=_pd_recoverable),
    Action("rebuild_start", "Start rebuild", "write", "pd", _build_pd_rebuild_start,
           "Manually initiate rebuild on this drive.",
           applicable=_pd_rebuildable),
    Action("rebuild_stop", "Stop rebuild", "destructive", "pd", _build_pd_rebuild_stop,
           "Abort an in-progress rebuild — array stays degraded.",
           applicable=_pd_is_rebuilding),
    Action("pd_offline", "PD Offline", "destructive", "pd", _build_pd_offline,
           "Force the drive offline. Removes redundancy if last good copy.",
           applicable=_pd_is_online),
    Action("pd_mark_missing", "Mark Missing", "destructive", "pd", _build_pd_mark_missing,
           "Mark drive missing (precondition for replace-missing).",
           applicable=_pd_is_offline),
    Action("pd_make_bad", "PD Make Bad", "destructive", "pd", _build_pd_make_bad,
           "Force the drive into a Bad state (Failed).",
           applicable=_pd_can_make_bad),
    Action("pd_clear_progress", "PD Clear progress", "safe", "pd", _build_pd_clear_progress,
           "Show progress of an in-progress PD Clear."),
    Action("pd_clear", "PD Clear (WIPE DATA)", "catastrophic", "pd", _build_pd_clear_start,
           "Initialise/erase the entire physical drive contents.",
           confirm_phrase="WIPE",
           applicable=_pd_clearable),
    Action("pd_create_r0", "Create single-disk RAID0 VD", "destructive", "pd",
           _build_pd_create_r0,
           "Wrap this drive in a new RAID0 logical drive (1 disk). Existing data is lost.",
           applicable=_pd_is_unconfigured_good),
]


# --------------------------------------------------------------------------- #
# LD actions
# --------------------------------------------------------------------------- #


def _build_ld_init_start(ld: LogicalDrive) -> list[str]:
    return ["-LDInit", "-Start", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_init_full(ld: LogicalDrive) -> list[str]:
    return ["-LDInit", "-Start", "-Full", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_init_stop(ld: LogicalDrive) -> list[str]:
    return ["-LDInit", "-Abort", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_init_progress(ld: LogicalDrive) -> list[str]:
    return ["-LDInit", "-ShowProg", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_cc_start(ld: LogicalDrive) -> list[str]:
    return ["-LDCC", "-Start", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_cc_stop(ld: LogicalDrive) -> list[str]:
    return ["-LDCC", "-Stop", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_cc_progress(ld: LogicalDrive) -> list[str]:
    return ["-LDCC", "-ShowProg", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_wb(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "WB", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_wt(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "WT", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_ra(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "ADRA", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_nora(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "NORA", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_cached(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "Cached", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_set_direct(ld: LogicalDrive) -> list[str]:
    return ["-LDSetProp", "Direct", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


def _build_ld_delete(ld: LogicalDrive) -> list[str]:
    return ["-CfgLdDel", f"-L{ld.ld_index}", f"-a{ld.adapter}"]


LD_ACTIONS: list[Action] = [
    Action("ld_init_progress", "Init progress", "safe", "ld", _build_ld_init_progress,
           "Show progress of background init / fast init."),
    Action("ld_cc_progress", "CC progress", "safe", "ld", _build_ld_cc_progress,
           "Show consistency-check progress."),
    Action("ld_cc_start", "Start consistency check", "write", "ld", _build_ld_cc_start,
           "Start a consistency check on this LD."),
    Action("ld_cc_stop", "Stop consistency check", "write", "ld", _build_ld_cc_stop,
           "Abort a running consistency check."),
    Action("ld_set_wb", "Cache: WriteBack", "write", "ld", _build_ld_set_wb,
           "Set write policy to WriteBack."),
    Action("ld_set_wt", "Cache: WriteThrough", "write", "ld", _build_ld_set_wt,
           "Set write policy to WriteThrough."),
    Action("ld_set_ra", "Read: Adaptive ReadAhead", "write", "ld", _build_ld_set_ra,
           "Enable adaptive read-ahead."),
    Action("ld_set_nora", "Read: No ReadAhead", "write", "ld", _build_ld_set_nora,
           "Disable read-ahead."),
    Action("ld_set_cached", "IO: Cached", "write", "ld", _build_ld_set_cached,
           "Use cached I/O policy."),
    Action("ld_set_direct", "IO: Direct", "write", "ld", _build_ld_set_direct,
           "Use direct I/O policy (bypass cache for reads)."),
    Action("ld_init_start", "Init (fast)", "destructive", "ld", _build_ld_init_start,
           "Fast-initialise: zero only metadata. Data may be unreadable."),
    Action("ld_init_full", "Init (FULL)", "destructive", "ld", _build_ld_init_full,
           "Full initialise: zero entire LD. Background, but irreversible."),
    Action("ld_init_stop", "Abort init", "write", "ld", _build_ld_init_stop,
           "Abort an in-progress LD init."),
    Action("ld_delete", "DELETE Logical Drive", "catastrophic", "ld", _build_ld_delete,
           "Delete this logical drive AND all data on it.",
           confirm_phrase="DELETE"),
]


# --------------------------------------------------------------------------- #
# Adapter actions
# --------------------------------------------------------------------------- #


def _build_pr_start(adapter: int) -> list[str]:
    return ["-AdpPR", "-Start", f"-a{adapter}"]


def _build_pr_stop(adapter: int) -> list[str]:
    return ["-AdpPR", "-Stop", f"-a{adapter}"]


def _build_pr_suspend(adapter: int) -> list[str]:
    return ["-AdpPR", "-Suspend", f"-a{adapter}"]


def _build_pr_resume(adapter: int) -> list[str]:
    return ["-AdpPR", "-Resume", f"-a{adapter}"]


def _build_pr_info(adapter: int) -> list[str]:
    return ["-AdpPR", "-Info", f"-a{adapter}"]


def _build_alarm_enable(adapter: int) -> list[str]:
    return ["-AdpSetProp", "AlarmEnbl", f"-a{adapter}"]


def _build_alarm_disable(adapter: int) -> list[str]:
    return ["-AdpSetProp", "AlarmDsbl", f"-a{adapter}"]


def _build_alarm_silence(adapter: int) -> list[str]:
    return ["-AdpSetProp", "AlarmSilence", f"-a{adapter}"]


def _build_bbu_learn(adapter: int) -> list[str]:
    return ["-AdpBbuCmd", "-BbuLearn", f"-a{adapter}"]


def _build_cfg_clear(adapter: int) -> list[str]:
    return ["-CfgLdDel", "-LALL", f"-a{adapter}"]


def _build_cfg_clear_full(adapter: int) -> list[str]:
    return ["-CfgClr", f"-a{adapter}"]


ADAPTER_ACTIONS: list[Action] = [
    Action("pr_info", "Patrol Read info", "safe", "adapter", _build_pr_info,
           "Show patrol-read schedule and progress."),
    Action("pr_start", "Patrol Read start", "write", "adapter", _build_pr_start,
           "Start a patrol-read pass now."),
    Action("pr_suspend", "Patrol Read suspend", "write", "adapter", _build_pr_suspend,
           "Suspend the active patrol read."),
    Action("pr_resume", "Patrol Read resume", "write", "adapter", _build_pr_resume,
           "Resume a suspended patrol read."),
    Action("pr_stop", "Patrol Read stop", "write", "adapter", _build_pr_stop,
           "Stop the active patrol read."),
    Action("alarm_silence", "Alarm: silence", "safe", "adapter", _build_alarm_silence,
           "Silence the controller alarm without changing config."),
    Action("alarm_enable", "Alarm: enable", "write", "adapter", _build_alarm_enable,
           "Enable the controller alarm."),
    Action("alarm_disable", "Alarm: disable", "write", "adapter", _build_alarm_disable,
           "Disable the controller alarm."),
    Action("bbu_learn", "BBU: start learn cycle", "write", "adapter", _build_bbu_learn,
           "Start a BBU learn cycle (battery cap test)."),
    Action("cfg_delete_all_lds", "Delete ALL Logical Drives", "catastrophic", "adapter",
           _build_cfg_clear,
           "Delete every logical drive on this adapter (data loss).",
           confirm_phrase="DELETE-ALL"),
    Action("cfg_clear", "CLEAR ENTIRE CONFIG", "catastrophic", "adapter",
           _build_cfg_clear_full,
           "Wipe RAID config (LDs, hot spares, foreign cfg). Cannot undo.",
           confirm_phrase="CLEAR-CONFIG"),
]


def actions_for(kind: TargetKind) -> list[Action]:
    if kind == "pd":
        return PD_ACTIONS
    if kind == "ld":
        return LD_ACTIONS
    return ADAPTER_ACTIONS


def applicable_actions(kind: TargetKind, target: object) -> list[Action]:
    """Return only actions whose `applicable` predicate (if any) accepts target."""
    out: list[Action] = []
    for a in actions_for(kind):
        if a.applicable is None or a.applicable(target):
            out.append(a)
    return out
