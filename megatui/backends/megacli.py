"""MegaCli64 backend — wraps the original text parsers."""
from __future__ import annotations

from typing import Any

from .. import parsers as P
from ..parsers import Adapter, BBUStatus, Enclosure, LogicalDrive, PhysicalDrive
from ..runner import Runner
from .base import Backend


DEFAULT_MEGACLI_PATH = "/opt/MegaRAID/MegaCli/MegaCli64"


def _megacli_fixture(args: list[str], fixtures_dir: str) -> str | None:
    joined = " ".join(args).lower()
    if "-pdlist" in joined:
        return "pdlist.txt"
    if "-ldinfo" in joined:
        return "ldinfo.txt"
    if "-adpallinfo" in joined:
        return "adpinfo.txt"
    if "-encinfo" in joined:
        return "encinfo.txt"
    if "-getbbustatus" in joined or "-adpbbucmd" in joined:
        return "bbu.txt"
    if "-adpcount" in joined:
        return "adpcount.txt"
    return None


# --------------------------------------------------------------------------- #
# argv builders — one per action_key
# --------------------------------------------------------------------------- #

def _physdrv(pd: PhysicalDrive) -> str:
    enc = pd.enclosure or "0"
    slot = pd.slot or pd.device_id or "0"
    return f"[{enc}:{slot}]"


def _pd(action: str, *extra: str):
    def build(pd: PhysicalDrive) -> list[str]:
        return [action, *extra, "-PhysDrv", _physdrv(pd), f"-a{pd.adapter}"]
    return build


def _ld(action: str, *extra: str):
    def build(ld: LogicalDrive) -> list[str]:
        return [action, *extra, f"-L{ld.ld_index}", f"-a{ld.adapter}"]
    return build


def _adp(*args: str):
    def build(adapter: int) -> list[str]:
        return [*args, f"-a{adapter}"]
    return build


MEGACLI_BUILDERS = {
    # PD actions
    "locate_on":        _pd("-PdLocate", "-start"),
    "locate_off":       _pd("-PdLocate", "-stop"),
    "hsp_set":          _pd("-PDHSP", "-Set"),
    "hsp_remove":       _pd("-PDHSP", "-Rmv"),
    "pd_online":        _pd("-PDOnline"),
    "pd_offline":       _pd("-PDOffline"),
    "pd_mark_missing":  _pd("-PDMarkMissing"),
    "pd_make_good":     _pd("-PDMakeGood"),
    "pd_make_bad":      _pd("-PDMakeBad"),
    "rebuild_start":    _pd("-PDRbld", "-Start"),
    "rebuild_stop":     _pd("-PDRbld", "-Stop"),
    "rebuild_progress": _pd("-PDRbld", "-ShowProg"),
    "pd_clear":         _pd("-PDClear", "-Start"),
    "pd_clear_progress":_pd("-PDClear", "-ShowProg"),
    "pd_create_r0":     lambda pd: ["-CfgLdAdd", "-r0", _physdrv(pd), f"-a{pd.adapter}"],

    # LD actions
    "ld_init_start":    _ld("-LDInit", "-Start"),
    "ld_init_full":     _ld("-LDInit", "-Start", "-Full"),
    "ld_init_stop":     _ld("-LDInit", "-Abort"),
    "ld_init_progress": _ld("-LDInit", "-ShowProg"),
    "ld_cc_start":      _ld("-LDCC", "-Start"),
    "ld_cc_stop":       _ld("-LDCC", "-Stop"),
    "ld_cc_progress":   _ld("-LDCC", "-ShowProg"),
    "ld_set_wb":        _ld("-LDSetProp", "WB"),
    "ld_set_wt":        _ld("-LDSetProp", "WT"),
    "ld_set_ra":        _ld("-LDSetProp", "ADRA"),
    "ld_set_nora":      _ld("-LDSetProp", "NORA"),
    "ld_set_cached":    _ld("-LDSetProp", "Cached"),
    "ld_set_direct":    _ld("-LDSetProp", "Direct"),
    "ld_delete":        _ld("-CfgLdDel"),

    # Adapter actions
    "pr_start":         _adp("-AdpPR", "-Start"),
    "pr_stop":          _adp("-AdpPR", "-Stop"),
    "pr_suspend":       _adp("-AdpPR", "-Suspend"),
    "pr_resume":        _adp("-AdpPR", "-Resume"),
    "pr_info":          _adp("-AdpPR", "-Info"),
    "alarm_enable":     _adp("-AdpSetProp", "AlarmEnbl"),
    "alarm_disable":    _adp("-AdpSetProp", "AlarmDsbl"),
    "alarm_silence":    _adp("-AdpSetProp", "AlarmSilence"),
    "bbu_learn":        _adp("-AdpBbuCmd", "-BbuLearn"),
    "cfg_delete_all_lds": _adp("-CfgLdDel", "-LALL"),
    "cfg_clear":        _adp("-CfgClr"),
}


class MegaCliBackend(Backend):
    name = "megacli"

    def __init__(
        self,
        *,
        binary: str = DEFAULT_MEGACLI_PATH,
        use_sudo: bool = True,
        fixtures_dir: str | None = None,
    ) -> None:
        self.runner = Runner(
            binary=binary,
            use_sudo=use_sudo,
            fixtures_dir=fixtures_dir,
            fixture_lookup=_megacli_fixture,
            append_args=["-NoLog"],
        )

    # -- read path ------------------------------------------------------ #

    def adp_count(self) -> int:
        r = self.runner.run(["-adpCount"])
        for line in r.stdout.splitlines():
            if "Controller Count" in line:
                _, _, rhs = line.partition(":")
                rhs = rhs.strip().rstrip(".")
                if rhs.isdigit():
                    return int(rhs)
        return 0

    def adapters(self) -> list[Adapter]:
        r = self.runner.run(["-AdpAllInfo", "-aALL"])
        return P.parse_adp_all_info(r.stdout) if r.ok else []

    def physical_drives(self) -> list[PhysicalDrive]:
        r = self.runner.run(["-PDList", "-aALL"])
        return P.parse_pdlist(r.stdout) if r.ok else []

    def logical_drives(self) -> list[LogicalDrive]:
        r = self.runner.run(["-LDInfo", "-Lall", "-aALL"])
        return P.parse_ldinfo(r.stdout) if r.ok else []

    def enclosures(self) -> list[Enclosure]:
        r = self.runner.run(["-EncInfo", "-aALL"])
        return P.parse_encinfo(r.stdout) if r.ok else []

    def bbu_statuses(self) -> list[BBUStatus]:
        r = self.runner.run(["-AdpBbuCmd", "-GetBbuStatus", "-aALL"])
        return P.parse_bbu(r.stdout or r.stderr)

    # -- write path ----------------------------------------------------- #

    def supports(self, action_key: str, target: Any = None) -> bool:
        if action_key in MEGACLI_BUILDERS:
            return True
        # Tool actions (sg_format) — delegate to base capability check.
        return super().supports(action_key, target)

    def build_argv(self, action_key: str, target: Any) -> list[str]:
        if action_key in MEGACLI_BUILDERS:
            return MEGACLI_BUILDERS[action_key](target)
        if self.tool_for(action_key) is not None:
            return self._tool_argv(action_key, target)
        raise NotImplementedError(f"megacli backend has no builder for {action_key}")
