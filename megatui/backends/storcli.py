"""storcli64 backend — speaks JSON, maps to the same dataclasses as MegaCli."""
from __future__ import annotations

import json
import re
from typing import Any

from ..parsers import Adapter, BBUStatus, Enclosure, LogicalDrive, PhysicalDrive
from ..runner import Result, Runner
from .base import Backend


DEFAULT_STORCLI_PATH = "/opt/MegaRAID/storcli/storcli64"


def _storcli_fixture(args: list[str], fixtures_dir: str) -> str | None:
    """Map storcli args (excluding trailing 'J') to a fixture filename.

    Tries `<name>` first and falls back to `storcli/<name>` so the same
    function works whether `--fixtures` points at the top-level fixtures
    directory or directly at the `storcli/` subdir.
    """
    import os as _os
    parts = [a for a in args if a != "J"]
    joined = " ".join(parts).lower()
    if "/c0/sall" in joined and "show" in joined:
        basename = "c0_sall_show_all.json"
    elif "/c0/vall" in joined and "show" in joined:
        basename = "c0_vall_show_all.json"
    elif "/c0/bbu" in joined and "show" in joined:
        basename = "c0_bbu_show_all.json"
    elif "/c0/eall/sall" in joined and "show" in joined:
        basename = "c0_eall_sall_show_all.json"
    elif "/c0/eall" in joined and "show" in joined:
        basename = "c0_eall_show_all.json"
    elif "/c0" in joined and "show" in joined and "all" in joined:
        basename = "c0_show_all.json"
    elif joined.strip().startswith("show all"):
        basename = "show_all.json"
    else:
        return None
    for candidate in (basename, _os.path.join("storcli", basename)):
        if _os.path.isfile(_os.path.join(fixtures_dir, candidate)):
            return candidate
    return None


# State code translation. Storcli uses short codes; we expand them so that
# the shared `applicable` predicates in actions.py (which look for substrings
# like "online", "unconfigured(good)", "failed", etc.) keep working.
_STATE_MAP = {
    "Onln": "Online",
    "Offln": "Offline",
    "UGood": "Unconfigured(good)",
    "UBad": "Unconfigured(bad)",
    "DHS": "Hotspare",
    "GHS": "Hotspare",
    "Rbld": "Rebuild",
    "Failed": "Failed",
    "Missing": "Missing",
    "JBOD": "JBOD",
    "Shielded": "Shielded",
    "Copyback": "Copyback",
}


def _normalize_state(code: str) -> str:
    code = (code or "").strip()
    return _STATE_MAP.get(code, code)


# --------------------------------------------------------------------------- #
# JSON parsers — return the same dataclasses as parsers.py
# --------------------------------------------------------------------------- #

def _response_data(blob: str) -> dict:
    """Extract the `Response Data` block, tolerating non-JSON error pages."""
    try:
        d = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return {}
    ctrls = d.get("Controllers") or []
    if not ctrls:
        return {}
    return ctrls[0].get("Response Data") or {}


def _response_status(blob: str) -> tuple[str, str]:
    try:
        d = json.loads(blob)
    except (json.JSONDecodeError, ValueError):
        return "", ""
    ctrls = d.get("Controllers") or []
    if not ctrls:
        return "", ""
    cs = ctrls[0].get("Command Status") or {}
    return cs.get("Status", ""), cs.get("Description", "")


def _raid_capable(rd: dict) -> bool:
    """Heuristic for 'does this controller actually do RAID volumes?'

    SAS3008-class cards in IT-mode firmware respond to /c0 show all with
    a Capabilities block that has no 'RAID Level Supported' key (and
    Max Strip Size like '512Bytes' which is nonsensical for RAID). True
    RAID controllers populate 'RAID Level Supported' with the supported
    set like 'RAID0, RAID1, RAID5, ...'. Use that as the indicator.
    """
    caps = rd.get("Capabilities", {}) or {}
    levels = caps.get("RAID Level Supported", "") or caps.get("RAID Level supported", "")
    return bool(str(levels).strip())


def parse_adp_all_info_json(blob: str, adapter_index: int = 0) -> list[Adapter]:
    rd = _response_data(blob)
    if not rd:
        return []
    basics = rd.get("Basics", {}) or {}
    version = rd.get("Version", {}) or {}
    hwcfg = rd.get("HwCfg", {}) or {}
    status = rd.get("Status", {}) or {}

    # Count drives / VDs from sibling commands? We only see /c0 show all here,
    # but PD/VD totals live elsewhere. We'll fill what's available locally.
    pdi = rd.get("Physical Device Information", {}) or {}
    pd_total = sum(1 for k in pdi.keys() if re.match(r"^Drive /c\d+/s\d+$", k))
    # No VD info inside this command; leave 0 unless surfaced elsewhere.

    bbu_field = str(hwcfg.get("BatteryFRU", "N/A")).strip()
    bbu_present = bbu_field not in {"N/A", "NA", "None", "-", ""}

    a = Adapter(index=adapter_index)
    flat = {
        "Product Name": str(basics.get("Model", "")).strip(),
        "Serial No": str(basics.get("Serial Number", "")).strip(),
        "FW Package Build": str(version.get("Firmware Package Build", "")).strip(),
        "FW Version": str(version.get("Firmware Version", "")).strip(),
        "BIOS Version": str(version.get("Bios Version", "")).strip(),
        "Memory Size": str(hwcfg.get("On Board Memory Size", "")).strip(),
        "BBU": "Present" if bbu_present else "Absent",
        "Physical Devices": str(pd_total),
        "Controller Status": str(status.get("Controller Status", "")).strip(),
        "Driver": str(version.get("Driver Name", "")).strip(),
        "Driver Version": str(version.get("Driver Version", "")).strip(),
        "SAS Address": str(basics.get("SAS Address", "")).strip(),
        "PCI Address": str(basics.get("PCI Address", "")).strip(),
        "Adapter Type": str(basics.get("Adapter Type", "")).strip(),
        "ROC Temperature": f"{hwcfg.get('ROC temperature(Degree Celsius)', '')}C"
            if hwcfg.get("ROC temperature(Degree Celsius)") not in (None, "") else "",
        "Flash Size": str(hwcfg.get("Flash Size", "")).strip(),
        "Front End Ports": str(hwcfg.get("Front End Port Count", "")).strip(),
        "Backend Ports": str(hwcfg.get("Backend Port Count", "")).strip(),
    }
    a.flat = {k: v for k, v in flat.items() if v}
    a.flat["RAID Capable"] = "Yes" if _raid_capable(rd) else "No"
    # Stash nested sections so the detail modal can show everything raw.
    for sec_name in ("Basics", "Version", "Status", "HwCfg", "Policies",
                     "Capabilities", "Supported Adapter Operations"):
        sec = rd.get(sec_name, {}) or {}
        if isinstance(sec, dict) and sec:
            a.sections[sec_name] = {k: str(v) for k, v in sec.items()}
    return [a]


_DRIVE_KEY_RE = re.compile(r"^Drive /c(\d+)/s(\d+)$")
_DETAIL_KEY_RE = re.compile(r"^Drive /c(\d+)/s(\d+) - Detailed Information$")


def parse_pdlist_json(blob: str) -> list[PhysicalDrive]:
    rd = _response_data(blob)
    if not rd:
        return []
    drives: dict[tuple[int, int], PhysicalDrive] = {}

    # Pass 1: summary rows (one per drive)
    for key, val in rd.items():
        m = _DRIVE_KEY_RE.match(key)
        if not m or not isinstance(val, list) or not val:
            continue
        controller, slot = int(m.group(1)), int(m.group(2))
        summary = val[0]
        pd = PhysicalDrive(adapter=controller)
        # Translate storcli summary fields into MegaCli-style keys so the
        # downstream UI and predicates work without changes.
        eid_slt = str(summary.get("EID:Slt", "")).strip()
        enc_part, _, slot_part = eid_slt.partition(":")
        enc_part = enc_part.strip()
        slot_part = slot_part.strip()
        pd.raw["Enclosure Device ID"] = enc_part if enc_part and enc_part != "-" else ""
        pd.raw["Slot Number"] = slot_part or str(slot)
        pd.raw["Device Id"] = str(summary.get("DID", slot))
        pd.raw["Firmware state"] = _normalize_state(str(summary.get("State", "")))
        pd.raw["Coerced Size"] = str(summary.get("Size", ""))
        pd.raw["Foreign State"] = "None"
        intf = str(summary.get("Intf", "")).strip()
        med = str(summary.get("Med", "")).strip()
        pd.raw["PD Type"] = intf
        pd.raw["Media Type"] = (
            "Hard Disk Device" if med.upper() == "HDD"
            else "Solid State Device" if med.upper() == "SSD"
            else med
        )
        pd.raw["Inquiry Data"] = str(summary.get("Model", "")).strip()
        pd.raw["Sector Size"] = str(summary.get("SeSz", "")).strip()
        drives[(controller, slot)] = pd

    # Pass 2: merge detailed information (richer fields for the detail modal)
    for key, val in rd.items():
        m = _DETAIL_KEY_RE.match(key)
        if not m or not isinstance(val, dict):
            continue
        controller, slot = int(m.group(1)), int(m.group(2))
        pd = drives.get((controller, slot))
        if pd is None:
            continue
        state_sec = val.get(f"Drive /c{controller}/s{slot} State", {}) or {}
        attrs_sec = val.get(f"Drive /c{controller}/s{slot} Device attributes", {}) or {}
        pols_sec = val.get(f"Drive /c{controller}/s{slot} Policies/Settings", {}) or {}

        # error counts (storcli reports N/A on IT-mode for unmanaged drives)
        for src, dst in [
            ("Shield Counter", "Shield Counter"),
            ("Media Error Count", "Media Error Count"),
            ("Other Error Count", "Other Error Count"),
            ("Predictive Failure Count", "Predictive Failure Count"),
        ]:
            v = state_sec.get(src)
            if v not in (None, "", "N/A"):
                pd.raw[dst] = str(v)
        smart = state_sec.get("S.M.A.R.T alert flagged by drive", "")
        if smart not in (None, "", "N/A"):
            pd.raw["Drive has flagged a S.M.A.R.T alert"] = str(smart)

        # device attributes
        attr_map = {
            "Manufacturer Id": None,  # merged into Inquiry below
            "Model Number": None,
            "SN": "Serial No",
            "WWN": "WWN",
            "Firmware Revision": "Device Firmware Level",
            "Raw size": "Raw Size",
            "Coerced size": "Coerced Size",
            "Non Coerced size": "Non Coerced Size",
            "Device Speed": "Device Speed",
            "Link Speed": "Link Speed",
            "Sector Size": "Sector Size",
            "Number of Blocks": "Number of Blocks",
            "Connector Name": "Connector Name",
        }
        for src, dst in attr_map.items():
            if dst is None:
                continue
            v = attrs_sec.get(src)
            if v not in (None, ""):
                pd.raw[dst] = str(v).strip()
        # Build a MegaCli-shaped Inquiry Data string when not already set.
        mfg = str(attrs_sec.get("Manufacturer Id", "")).strip()
        model = str(attrs_sec.get("Model Number", "")).strip()
        fw_rev = str(attrs_sec.get("Firmware Revision", "")).strip()
        if mfg or model:
            pd.raw["Inquiry Data"] = f"{mfg:<8}{model:<16}{fw_rev}".strip()

        # policies / port info
        for src, dst in [
            ("Enclosure position", "Enclosure position"),
            ("Connected Port Number", "Connected Port Number"),
            ("Sequence Number", "Sequence Number"),
            ("Commissioned Spare", "Commissioned Spare"),
            ("Emergency Spare", "Emergency Spare"),
            ("Certified", "Drive"),
            ("Multipath", "Multipath"),
        ]:
            v = pols_sec.get(src)
            if v not in (None, "", "N/A"):
                pd.raw[dst] = str(v).strip()
        # Port table → SAS Address(0) / SAS Address(1)
        for i, port in enumerate(pols_sec.get("Port Information", []) or []):
            sas = str(port.get("SAS address", "")).strip()
            if sas:
                pd.raw[f"SAS Address({i})"] = sas
        # Inquiry (hex) — leave as raw for the detail modal
        hex_inq = val.get("Inquiry Data")
        if isinstance(hex_inq, str) and hex_inq.strip():
            pd.raw["Inquiry Data (hex)"] = hex_inq.strip()

    return list(drives.values())


def parse_ldinfo_json(blob: str) -> list[LogicalDrive]:
    rd = _response_data(blob)
    if not rd:
        return []
    lds: list[LogicalDrive] = []
    vd_re = re.compile(r"^/c(\d+)/v(\d+)$")
    vd_detail_re = re.compile(r"^VD(\d+) Properties$")
    # storcli /c0/vall outputs VD summary table and per-VD property sections.
    # We don't yet have a real-VD fixture; the parser is defensive.
    for key, val in rd.items():
        m = vd_re.match(key)
        if m and isinstance(val, list) and val:
            row = val[0]
            ld = LogicalDrive(
                adapter=int(m.group(1)),
                ld_index=m.group(2),
            )
            ld.raw["Name"] = str(row.get("Name", "")).strip()
            ld.raw["RAID Level"] = str(row.get("TYPE", row.get("Type", ""))).strip()
            ld.raw["Size"] = str(row.get("Size", "")).strip()
            ld.raw["State"] = str(row.get("State", "")).strip()
            ld.raw["Number Of Drives"] = str(row.get("DRIVE", row.get("Drives", ""))).strip()
            ld.raw["Current Cache Policy"] = (
                f"{row.get('Cache', '').strip()} / {row.get('Access', '').strip()}"
            )
            lds.append(ld)
            continue
        m2 = vd_detail_re.match(key)
        if m2 and isinstance(val, dict):
            idx = m2.group(1)
            for ld in lds:
                if ld.ld_index == idx:
                    for k, v in val.items():
                        ld.raw.setdefault(k, str(v))
    return lds


def parse_encinfo_json(blob: str) -> list[Enclosure]:
    rd = _response_data(blob)
    if not rd:
        return []
    encs: list[Enclosure] = []
    enc_re = re.compile(r"^Enclosure /c(\d+)/e(\d+)")
    for key, val in rd.items():
        m = enc_re.match(key)
        if m and isinstance(val, list) and val:
            row = val[0]
            e = Enclosure(adapter=int(m.group(1)), index=m.group(2))
            e.raw["Device ID"] = str(row.get("EID", m.group(2)))
            e.raw["Number of Slots"] = str(row.get("Slots", ""))
            e.raw["Status"] = str(row.get("State", ""))
            e.raw["Enclosure type"] = str(row.get("Type", ""))
            encs.append(e)
    return encs


def parse_bbu_json(blob: str, adapter_index: int = 0) -> list[BBUStatus]:
    rd = _response_data(blob)
    status, desc = _response_status(blob)
    if not rd:
        # BBU section was unsupported (typical for HBA-only controllers)
        return [BBUStatus(
            adapter=adapter_index,
            present=False,
            error=desc or status or "BBU not present",
        )]
    bbu_info = rd.get("BBU_Info", rd.get("BBU Info", {})) or {}
    if not bbu_info:
        return [BBUStatus(adapter=adapter_index, present=False, error="BBU not present")]
    s = BBUStatus(adapter=adapter_index, present=True)
    s.raw = {k: str(v) for k, v in bbu_info.items()}
    return [s]


# --------------------------------------------------------------------------- #
# argv builders
# --------------------------------------------------------------------------- #

def _pd_path(pd: PhysicalDrive) -> str:
    """Build the /cN/sN or /cN/eE/sS path for a PD."""
    enc = (pd.enclosure or "").strip()
    slot = pd.slot or pd.device_id or "0"
    if enc and enc not in {"-", "0", ""}:
        return f"/c{pd.adapter}/e{enc}/s{slot}"
    return f"/c{pd.adapter}/s{slot}"


def _ld_path(ld: LogicalDrive) -> str:
    return f"/c{ld.adapter}/v{ld.ld_index}"


def _bbu_path(adapter: int) -> str:
    return f"/c{adapter}/bbu"


def _adp_path(adapter: int) -> str:
    return f"/c{adapter}"


def _pd_op(*verbs: str):
    def build(pd: PhysicalDrive) -> list[str]:
        return [_pd_path(pd), *verbs]
    return build


def _ld_op(*verbs: str):
    def build(ld: LogicalDrive) -> list[str]:
        return [_ld_path(ld), *verbs]
    return build


def _adp_op(*verbs: str):
    def build(adapter: int) -> list[str]:
        return [_adp_path(adapter), *verbs]
    return build


def _build_storcli_create_r0(pd: PhysicalDrive) -> list[str]:
    """`add vd` for a single drive. Help syntax is `drives=[e:]s` — the
    enclosure prefix is optional, so for direct-attach drives we omit it
    entirely. Sending `drives=:N` triggers storcli's parser to bail with
    'unexpected TOKEN_COLON'."""
    enc = (pd.enclosure or "").strip()
    slot = pd.slot or pd.device_id or "0"
    if enc and enc not in {"-", ""}:
        drives_spec = f"{enc}:{slot}"
    else:
        drives_spec = slot
    return [f"/c{pd.adapter}", "add", "vd", "r0", f"drives={drives_spec}"]


def _build_storcli_bbu_learn(adapter: int) -> list[str]:
    return [_bbu_path(adapter), "start", "learn"]


def _build_storcli_cfg_clear(adapter: int) -> list[str]:
    return [_adp_path(adapter), "delete", "config", "force"]


def _build_storcli_cfg_delete_all_lds(adapter: int) -> list[str]:
    return [f"/c{adapter}/vall", "del", "force"]


STORCLI_BUILDERS = {
    # PD
    "locate_on":        _pd_op("start", "locate"),
    "locate_off":       _pd_op("stop", "locate"),
    "hsp_set":          _pd_op("add", "hotsparedrive"),
    "hsp_remove":       _pd_op("delete", "hotsparedrive"),
    "pd_online":        _pd_op("set", "online"),
    "pd_offline":       _pd_op("set", "offline"),
    "pd_mark_missing":  _pd_op("set", "missing"),
    "pd_make_good":     _pd_op("set", "good", "force"),
    "pd_make_bad":      _pd_op("set", "bad", "force"),
    "rebuild_start":    _pd_op("start", "rebuild"),
    "rebuild_stop":     _pd_op("stop", "rebuild"),
    "rebuild_progress": _pd_op("show", "rebuild"),
    "pd_clear":         _pd_op("start", "initialization"),
    "pd_clear_progress":_pd_op("show", "initialization"),
    "pd_create_r0":     _build_storcli_create_r0,
    # LD
    "ld_init_start":    _ld_op("start", "init"),
    "ld_init_full":     _ld_op("start", "init", "full"),
    "ld_init_stop":     _ld_op("stop", "init"),
    "ld_init_progress": _ld_op("show", "init"),
    "ld_cc_start":      _ld_op("start", "cc"),
    "ld_cc_stop":       _ld_op("stop", "cc"),
    "ld_cc_progress":   _ld_op("show", "cc"),
    "ld_set_wb":        _ld_op("set", "wrcache=wb"),
    "ld_set_wt":        _ld_op("set", "wrcache=wt"),
    "ld_set_ra":        _ld_op("set", "rdcache=ra"),
    "ld_set_nora":      _ld_op("set", "rdcache=nora"),
    "ld_set_cached":    _ld_op("set", "iopolicy=cached"),
    "ld_set_direct":    _ld_op("set", "iopolicy=direct"),
    "ld_delete":        _ld_op("del", "force"),
    # Adapter
    "pr_start":         _adp_op("start", "patrolread"),
    "pr_stop":          _adp_op("stop", "patrolread"),
    "pr_suspend":       _adp_op("suspend", "patrolread"),
    "pr_resume":        _adp_op("resume", "patrolread"),
    "pr_info":          _adp_op("show", "patrolread"),
    "alarm_enable":     _adp_op("set", "alarm=on"),
    "alarm_disable":    _adp_op("set", "alarm=off"),
    "alarm_silence":    _adp_op("set", "alarm=silence"),
    "bbu_learn":        _build_storcli_bbu_learn,
    "cfg_delete_all_lds": _build_storcli_cfg_delete_all_lds,
    "cfg_clear":        _build_storcli_cfg_clear,
}


class StorcliBackend(Backend):
    name = "storcli"

    # Actions that only work on RAID-capable controllers. supports() returns
    # False for these when the target's adapter is in the non-RAID set.
    _RAID_ONLY_ACTIONS = frozenset({
        "pd_create_r0", "hsp_set", "hsp_remove",
        "rebuild_start", "rebuild_stop", "rebuild_progress",
        "pd_online", "pd_offline", "pd_mark_missing",
        "pd_make_good", "pd_make_bad",
        "pd_clear", "pd_clear_progress",
        "ld_init_start", "ld_init_full", "ld_init_stop", "ld_init_progress",
        "ld_cc_start", "ld_cc_stop", "ld_cc_progress",
        "ld_set_wb", "ld_set_wt", "ld_set_ra", "ld_set_nora",
        "ld_set_cached", "ld_set_direct", "ld_delete",
        "pr_start", "pr_stop", "pr_suspend", "pr_resume", "pr_info",
        "bbu_learn", "cfg_delete_all_lds", "cfg_clear",
    })

    def __init__(
        self,
        *,
        binary: str = DEFAULT_STORCLI_PATH,
        use_sudo: bool = True,
        fixtures_dir: str | None = None,
    ) -> None:
        # Every storcli invocation gets `J` appended for JSON output (idempotent).
        self.runner = Runner(
            binary=binary,
            use_sudo=use_sudo,
            fixtures_dir=fixtures_dir,
            fixture_lookup=_storcli_fixture,
            append_args=["J"],
        )
        # Per-adapter RAID-capability cache; populated by adapters() / refresh.
        self._raid_capable_adapters: set[int] = set()

    # -- read path ------------------------------------------------------ #

    def adp_count(self) -> int:
        r = self.runner.run(["show", "all"])
        rd = _response_data(r.stdout)
        sysinfo = rd.get("System Overview", []) or rd.get("Number of Controllers", 0)
        if isinstance(sysinfo, list):
            return len(sysinfo)
        if isinstance(sysinfo, int):
            return sysinfo
        # Fallback: rely on /c0 being present
        return 1 if "/c0" in r.stdout else 0

    def adapters(self) -> list[Adapter]:
        r = self.runner.run(["/c0", "show", "all"])
        adps = parse_adp_all_info_json(r.stdout, adapter_index=0)
        # Cache RAID capability per adapter so supports() can hide RAID-only
        # actions on cards (e.g. SAS3008 IT-firmware) that would reject them.
        self._raid_capable_adapters = {
            a.index for a in adps if a.flat.get("RAID Capable") == "Yes"
        }
        return adps

    def physical_drives(self) -> list[PhysicalDrive]:
        r = self.runner.run(["/c0/sall", "show", "all"])
        return parse_pdlist_json(r.stdout)

    def logical_drives(self) -> list[LogicalDrive]:
        r = self.runner.run(["/c0/vall", "show", "all"])
        # storcli returns Failure / Un-supported when no VDs exist — that maps
        # cleanly to an empty list.
        return parse_ldinfo_json(r.stdout)

    def enclosures(self) -> list[Enclosure]:
        r = self.runner.run(["/c0/eall", "show", "all"])
        return parse_encinfo_json(r.stdout)

    def bbu_statuses(self) -> list[BBUStatus]:
        r = self.runner.run(["/c0/bbu", "show", "all"])
        return parse_bbu_json(r.stdout, adapter_index=0)

    # -- write path ----------------------------------------------------- #

    def supports(self, action_key: str, target: Any = None) -> bool:
        if action_key not in STORCLI_BUILDERS:
            return False
        if action_key in self._RAID_ONLY_ACTIONS:
            adapter = self._target_adapter(target)
            if adapter is not None and adapter not in self._raid_capable_adapters:
                return False
        return True

    @staticmethod
    def _target_adapter(target: Any) -> int | None:
        if target is None:
            return None
        if isinstance(target, int):
            return target
        return getattr(target, "adapter", None)

    def build_argv(self, action_key: str, target: Any) -> list[str]:
        builder = STORCLI_BUILDERS.get(action_key)
        if builder is None:
            raise NotImplementedError(f"storcli backend has no builder for {action_key}")
        return builder(target)
