"""Action metadata (key, title, danger, applicability).

Each Action declares *what* an operation is. The argv translation lives
inside each Backend (`megatui.backends.megacli` / `megatui.backends.storcli`)
because MegaCli64 and storcli64 speak different syntaxes for the same
logical operation.

Danger ratings:
    safe          — no data loss possible (locate LED, status queries)
    write         — changes runtime config (rates, hot-spare role, policies)
    destructive   — likely loses redundancy or interrupts I/O (offline, abort init)
    catastrophic  — destroys data or whole config (cfg clear, ld delete, pd clear)

Catastrophic actions require typed confirmation matching `confirm_phrase`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from .parsers import PhysicalDrive


Danger = Literal["safe", "write", "destructive", "catastrophic"]
TargetKind = Literal["pd", "ld", "adapter"]


@dataclass(frozen=True)
class Action:
    key: str
    title: str
    danger: Danger
    target: TargetKind
    summary: str = ""
    confirm_phrase: str = ""  # if non-empty, user must type this verbatim
    applicable: Callable[..., bool] | None = None  # gate visibility by target state


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
    return _pd_is_failed(pd) or _pd_is_unconfigured_bad(pd) or _pd_has_foreign(pd)


def _pd_rebuildable(pd: PhysicalDrive) -> bool:
    return _pd_is_failed(pd) or _pd_is_offline(pd) or _pd_is_unconfigured_bad(pd)


def _pd_can_make_bad(pd: PhysicalDrive) -> bool:
    return _pd_is_online(pd) or _pd_is_unconfigured_good(pd) or _pd_is_hotspare(pd)


def _pd_clearable(pd: PhysicalDrive) -> bool:
    return _pd_is_unconfigured_good(pd) or _pd_is_unconfigured_bad(pd)


# --------------------------------------------------------------------------- #
# Action catalogues
# --------------------------------------------------------------------------- #

PD_ACTIONS: list[Action] = [
    Action("locate_on", "Locate LED ON", "safe", "pd",
           "Blink the slot LED to physically locate the drive."),
    Action("locate_off", "Locate LED OFF", "safe", "pd",
           "Stop the locate LED."),
    Action("rebuild_progress", "Rebuild progress", "safe", "pd",
           "Show current rebuild percentage / ETA."),
    Action("hsp_set", "Set as Global Hot Spare", "write", "pd",
           "Configure this drive as a global hot spare.",
           applicable=_pd_is_unconfigured_good),
    Action("hsp_remove", "Remove Hot Spare role", "write", "pd",
           "Demote this hot spare back to Unconfigured Good.",
           applicable=_pd_is_hotspare),
    Action("pd_online", "PD Online", "write", "pd",
           "Force the drive online (use only if firmware state allows).",
           applicable=_pd_is_offline),
    Action("pd_make_good", "PD Make Good", "write", "pd",
           "Mark a foreign / failed drive as Unconfigured Good.",
           applicable=_pd_recoverable),
    Action("rebuild_start", "Start rebuild", "write", "pd",
           "Manually initiate rebuild on this drive.",
           applicable=_pd_rebuildable),
    Action("rebuild_stop", "Stop rebuild", "destructive", "pd",
           "Abort an in-progress rebuild — array stays degraded.",
           applicable=_pd_is_rebuilding),
    Action("pd_offline", "PD Offline", "destructive", "pd",
           "Force the drive offline. Removes redundancy if last good copy.",
           applicable=_pd_is_online),
    Action("pd_mark_missing", "Mark Missing", "destructive", "pd",
           "Mark drive missing (precondition for replace-missing).",
           applicable=_pd_is_offline),
    Action("pd_make_bad", "PD Make Bad", "destructive", "pd",
           "Force the drive into a Bad state (Failed).",
           applicable=_pd_can_make_bad),
    Action("pd_clear_progress", "PD Clear progress", "safe", "pd",
           "Show progress of an in-progress PD Clear."),
    Action("pd_clear", "PD Clear (WIPE DATA)", "catastrophic", "pd",
           "Initialise/erase the entire physical drive contents.",
           confirm_phrase="WIPE",
           applicable=_pd_clearable),
    Action("pd_create_r0", "Create single-disk RAID0 VD", "destructive", "pd",
           "Wrap this drive in a new RAID0 logical drive (1 disk). Existing data is lost.",
           applicable=_pd_is_unconfigured_good),
]


LD_ACTIONS: list[Action] = [
    Action("ld_init_progress", "Init progress", "safe", "ld",
           "Show progress of background init / fast init."),
    Action("ld_cc_progress", "CC progress", "safe", "ld",
           "Show consistency-check progress."),
    Action("ld_cc_start", "Start consistency check", "write", "ld",
           "Start a consistency check on this LD."),
    Action("ld_cc_stop", "Stop consistency check", "write", "ld",
           "Abort a running consistency check."),
    Action("ld_set_wb", "Cache: WriteBack", "write", "ld",
           "Set write policy to WriteBack."),
    Action("ld_set_wt", "Cache: WriteThrough", "write", "ld",
           "Set write policy to WriteThrough."),
    Action("ld_set_ra", "Read: Adaptive ReadAhead", "write", "ld",
           "Enable adaptive read-ahead."),
    Action("ld_set_nora", "Read: No ReadAhead", "write", "ld",
           "Disable read-ahead."),
    Action("ld_set_cached", "IO: Cached", "write", "ld",
           "Use cached I/O policy."),
    Action("ld_set_direct", "IO: Direct", "write", "ld",
           "Use direct I/O policy (bypass cache for reads)."),
    Action("ld_init_start", "Init (fast)", "destructive", "ld",
           "Fast-initialise: zero only metadata. Data may be unreadable."),
    Action("ld_init_full", "Init (FULL)", "destructive", "ld",
           "Full initialise: zero entire LD. Background, but irreversible."),
    Action("ld_init_stop", "Abort init", "write", "ld",
           "Abort an in-progress LD init."),
    Action("ld_delete", "DELETE Logical Drive", "catastrophic", "ld",
           "Delete this logical drive AND all data on it.",
           confirm_phrase="DELETE"),
]


ADAPTER_ACTIONS: list[Action] = [
    Action("pr_info", "Patrol Read info", "safe", "adapter",
           "Show patrol-read schedule and progress."),
    Action("pr_start", "Patrol Read start", "write", "adapter",
           "Start a patrol-read pass now."),
    Action("pr_suspend", "Patrol Read suspend", "write", "adapter",
           "Suspend the active patrol read."),
    Action("pr_resume", "Patrol Read resume", "write", "adapter",
           "Resume a suspended patrol read."),
    Action("pr_stop", "Patrol Read stop", "write", "adapter",
           "Stop the active patrol read."),
    Action("alarm_silence", "Alarm: silence", "safe", "adapter",
           "Silence the controller alarm without changing config."),
    Action("alarm_enable", "Alarm: enable", "write", "adapter",
           "Enable the controller alarm."),
    Action("alarm_disable", "Alarm: disable", "write", "adapter",
           "Disable the controller alarm."),
    Action("bbu_learn", "BBU: start learn cycle", "write", "adapter",
           "Start a BBU learn cycle (battery cap test)."),
    Action("cfg_delete_all_lds", "Delete ALL Logical Drives", "catastrophic", "adapter",
           "Delete every logical drive on this adapter (data loss).",
           confirm_phrase="DELETE-ALL"),
    Action("cfg_clear", "CLEAR ENTIRE CONFIG", "catastrophic", "adapter",
           "Wipe RAID config (LDs, hot spares, foreign cfg). Cannot undo.",
           confirm_phrase="CLEAR-CONFIG"),
]


def actions_for(kind: TargetKind) -> list[Action]:
    if kind == "pd":
        return PD_ACTIONS
    if kind == "ld":
        return LD_ACTIONS
    return ADAPTER_ACTIONS


def applicable_actions(kind: TargetKind, target: Any, backend: Any = None) -> list[Action]:
    """Return actions whose `applicable` predicate accepts target AND that the
    backend (if given) can execute. Without a backend the result still
    reflects state-based applicability, which is useful for tests."""
    out: list[Action] = []
    for a in actions_for(kind):
        if a.applicable is not None and not a.applicable(target):
            continue
        if backend is not None and not backend.supports(a.key):
            continue
        out.append(a)
    return out
