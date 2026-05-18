"""sas2ircu / sas3ircu backend.

Targets LSI/Broadcom IT- and IR-mode mpt2sas / mpt3sas HBAs (SAS2008 /
SAS2308 / SAS3008 / SAS3108 chips, e.g. 9201/9207/9211/9217 (SAS2)
and 9300/9305/9311/9341 (SAS3)). Both `sas2ircu` and `sas3ircu` share
the exact same command set; this backend picks whichever binary is
installed and prefers sas3ircu for newer cards.

Capability ceiling is much lower than storcli/MegaCli: ircu supports
LOCATE, HOTSPARE, CREATE (IR volumes), DELETE, and STATUS — nothing
else. backend.supports() filters the action menu accordingly.

DISPLAY output is line-oriented `key : value` with `----` section
dividers. Stable across firmware releases since ~2010, so the parser
is conservative and tolerates unknown fields by falling through into
the raw dict (consumed by the detail modal).
"""
from __future__ import annotations

import os
import re
import shutil
from typing import Any

from ..parsers import Adapter, BBUStatus, Enclosure, LogicalDrive, PhysicalDrive
from ..runner import Runner
from .base import Backend


DEFAULT_SAS3IRCU_PATH = "/usr/sbin/sas3ircu"
DEFAULT_SAS2IRCU_PATH = "/usr/sbin/sas2ircu"


def find_ircu_binary() -> str | None:
    """Return path to sas3ircu (preferred) or sas2ircu, or None."""
    for candidate in (
        DEFAULT_SAS3IRCU_PATH,
        DEFAULT_SAS2IRCU_PATH,
        "/opt/sas3ircu/sas3ircu",
        "/opt/sas2ircu/sas2ircu",
        "/usr/local/sbin/sas3ircu",
        "/usr/local/sbin/sas2ircu",
        "/usr/local/bin/sas3ircu",
        "/usr/local/bin/sas2ircu",
    ):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    for name in ("sas3ircu", "sas2ircu"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _ircu_fixture(args: list[str], fixtures_dir: str) -> str | None:
    """Map ircu args to a fixture filename, tolerating top-dir or ircu/ subdir."""
    joined = " ".join(args).lower()
    if "list" in joined and len(args) <= 2:
        basename = "list.txt"
    elif "display" in joined:
        basename = "display.txt"
    elif "status" in joined:
        basename = "status.txt"
    else:
        return None
    for candidate in (basename, os.path.join("ircu", basename)):
        if os.path.isfile(os.path.join(fixtures_dir, candidate)):
            return candidate
    return None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_KV_RE = re.compile(r"^\s*([A-Za-z][^:]*?)\s*:\s*(.*?)\s*$")
_SECTION_RE = re.compile(r"^-{10,}\s*$")
_HEADER_LINES = {
    "controller information",
    "ir volume information",
    "physical device information",
    "enclosure information",
}

# ircu reports states with short tags after the human name.
# e.g. "Ready (RDY)", "Online (ONL)", "Hot Spare (HSP)", "Failed (FLD)",
# "Missing (MIS)", "Initializing (INIT)", "Optimal (OPT)", "Degraded (DGD)".
_STATE_NORMALIZE = {
    "RDY": "Unconfigured(good)",
    "ONL": "Online",
    "HSP": "Hotspare",
    "FLD": "Failed",
    "MIS": "Missing",
    "OFL": "Offline",
    "OUT": "Offline",
    "STBY": "Standby",
    "RBLD": "Rebuild",
    "OPT": "Online",
    "DGD": "Degraded",
    "FLD2": "Failed",
    # IR volume status codes
    "OKY": "Optimal",
    "INACT": "Inactive",
    "FAIL": "Failed",
    "RT": "Rebuilding",
}


def _normalize_pd_state(raw: str) -> str:
    """Map ircu state strings to MegaCli-style canonical states."""
    m = re.match(r"^(.*?)\s*\(([A-Z]+)\)\s*$", raw or "")
    if m:
        code = m.group(2)
        if code in _STATE_NORMALIZE:
            return _STATE_NORMALIZE[code]
    return raw


def _split_sections(text: str) -> dict[str, list[str]]:
    """Split DISPLAY output by the '-----' divider headers into sections."""
    out: dict[str, list[str]] = {}
    current_header = "_preamble"
    current_lines: list[str] = []
    prev_dash = False
    for raw in text.splitlines():
        line = raw.rstrip()
        if _SECTION_RE.match(line):
            prev_dash = True
            continue
        if prev_dash:
            heading = line.strip().lower()
            if heading in _HEADER_LINES:
                if current_lines:
                    out.setdefault(current_header, []).extend(current_lines)
                current_header = heading
                current_lines = []
                prev_dash = False
                continue
            # dash but next line wasn't a known heading — likely a closing
            # divider; flush and keep accumulating in the same section.
            prev_dash = False
        current_lines.append(line)
    if current_lines:
        out.setdefault(current_header, []).extend(current_lines)
    return out


def parse_display(text: str, adapter_index: int = 0
                  ) -> tuple[list[Adapter], list[PhysicalDrive],
                             list[LogicalDrive], list[Enclosure]]:
    sections = _split_sections(text)

    # --- Controller information --- #
    adapters: list[Adapter] = []
    ctrl_lines = sections.get("controller information", [])
    if ctrl_lines:
        a = Adapter(index=adapter_index)
        sec: dict[str, str] = {}
        for line in ctrl_lines:
            m = _KV_RE.match(line)
            if m:
                sec[m.group(1).strip()] = m.group(2).strip()
        if sec:
            a.sections["Controller information"] = sec
            # Map ircu's keys → the flat keys the TUI expects.
            flat = {
                "Product Name": sec.get("Controller type", ""),
                "Adapter Type": sec.get("Controller type", ""),
                "FW Version": sec.get("Firmware version", ""),
                "BIOS Version": sec.get("BIOS version", ""),
                "Bus": sec.get("Bus", ""),
                "Device": sec.get("Device", ""),
                "Function": sec.get("Function", ""),
                "PCI Address": (
                    f"{sec.get('Bus', '?')}:{sec.get('Device', '?')}."
                    f"{sec.get('Function', '?')}"
                    if sec.get("Bus") else ""
                ),
                "Channel Description": sec.get("Channel description", ""),
                "RAID Support": sec.get("RAID Support", ""),
                "Slot": sec.get("Slot", ""),
            }
            a.flat = {k: v for k, v in flat.items() if v}
            adapters.append(a)

    # --- Physical device information --- #
    pds: list[PhysicalDrive] = []
    encs_seen: set[tuple[int, str]] = set()
    pd_lines = sections.get("physical device information", [])
    current: PhysicalDrive | None = None
    for line in pd_lines:
        stripped = line.strip()
        # New device boundary: header like "Device is a Hard disk", "Device is a SSD",
        # "Device is an Enclosure services device", "Device is a Tape drive".
        if stripped.lower().startswith("device is "):
            if current is not None and current.raw:
                pds.append(current)
            kind = stripped[len("device is "):].lstrip("a ").lstrip("an ").strip()
            current = PhysicalDrive(adapter=adapter_index)
            current.raw["PD Type"] = "SAS"           # default; refined below
            if "tape" in kind.lower():
                current.raw["PD Type"] = "Tape"
                current.raw["SCSI Device Type"] = "Tape"
            elif "enclosure" in kind.lower():
                # ircu lists expander/SES devices in the same section — skip.
                current = None
            elif "ssd" in kind.lower():
                current.raw["Media Type"] = "Solid State Device"
            else:
                current.raw["Media Type"] = "Hard Disk Device"
            continue
        # "Initiator at ID #0" — ignore
        if stripped.lower().startswith("initiator at id"):
            current = None
            continue
        m = _KV_RE.match(line)
        if m is None or current is None:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key == "Enclosure #":
            current.raw["Enclosure Device ID"] = val
        elif key == "Slot #":
            current.raw["Slot Number"] = val
            # ircu has no separate Device Id; reuse slot for stable identity.
            current.raw.setdefault("Device Id", val)
        elif key == "SAS Address":
            current.raw["SAS Address(0)"] = val.replace("-", "")
        elif key == "State":
            current.raw["Firmware state"] = _normalize_pd_state(val)
        elif key == "Size (in MB)/(in sectors)":
            mb, _, sectors = val.partition("/")
            mb = mb.strip()
            try:
                gb = int(mb) / 1024
                if gb >= 1000:
                    current.raw["Coerced Size"] = f"{gb / 1024:.3f} TB"
                else:
                    current.raw["Coerced Size"] = f"{gb:.3f} GB"
            except ValueError:
                current.raw["Coerced Size"] = val
            current.raw["Raw Size"] = val
        elif key == "Manufacturer":
            current.raw.setdefault("_mfg", val)
        elif key == "Model Number":
            current.raw.setdefault("_model", val)
        elif key == "Firmware Revision":
            current.raw["Device Firmware Level"] = val
        elif key == "Serial No":
            current.raw["Serial No"] = val
        elif key == "GUID":
            current.raw["WWN"] = val
        elif key == "Protocol":
            current.raw["PD Type"] = val.strip() or current.raw["PD Type"]
        elif key == "Drive Type":
            # SAS_HDD / SAS_SSD / SATA_HDD / SATA_SSD
            if "SSD" in val:
                current.raw["Media Type"] = "Solid State Device"
            elif "HDD" in val:
                current.raw["Media Type"] = "Hard Disk Device"
        else:
            current.raw.setdefault(key, val)
        current.raw["Foreign State"] = "None"
    if current is not None and current.raw:
        pds.append(current)

    # Build Inquiry Data from the captured mfg/model so the UI shows something
    # familiar (matches MegaCli/storcli layout).
    for p in pds:
        mfg = p.raw.pop("_mfg", "")
        model = p.raw.pop("_model", "")
        fw_rev = p.raw.get("Device Firmware Level", "")
        if mfg or model:
            p.raw["Inquiry Data"] = f"{mfg:<8}{model:<16}{fw_rev}".strip()
        encs_seen.add((p.adapter, p.enclosure))

    # --- IR Volume information → LogicalDrives --- #
    lds: list[LogicalDrive] = []
    vol_lines = sections.get("ir volume information", [])
    if any("no volumes" not in ln.lower() for ln in vol_lines) and \
       any("volume" in ln.lower() and ":" in ln for ln in vol_lines):
        # Multi-volume parsing: each "IR volume #N" starts a new LD.
        current_ld: LogicalDrive | None = None
        for line in vol_lines:
            m_hdr = re.match(r"^\s*IR volume\s*#?\s*(\d+)", line, re.IGNORECASE)
            if m_hdr:
                if current_ld is not None and current_ld.raw:
                    lds.append(current_ld)
                current_ld = LogicalDrive(
                    adapter=adapter_index, ld_index=m_hdr.group(1)
                )
                continue
            m = _KV_RE.match(line)
            if m is None or current_ld is None:
                continue
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key == "RAID level":
                current_ld.raw["RAID Level"] = val
            elif key == "Size (in MB)":
                current_ld.raw["Size"] = f"{val} MB"
            elif key == "Status of volume":
                current_ld.raw["State"] = _normalize_pd_state(val)
            elif key == "Name":
                current_ld.raw["Name"] = val
            elif key == "Number of PDs":
                current_ld.raw["Number Of Drives"] = val
            else:
                current_ld.raw[key] = val
        if current_ld is not None and current_ld.raw:
            lds.append(current_ld)

    # --- Enclosure information --- #
    encs: list[Enclosure] = []
    enc_lines = sections.get("enclosure information", [])
    current_enc: Enclosure | None = None
    for line in enc_lines:
        m = _KV_RE.match(line)
        if m is None:
            continue
        key = m.group(1).strip()
        val = m.group(2).strip()
        if key == "Enclosure#":
            if current_enc is not None and current_enc.raw:
                encs.append(current_enc)
            current_enc = Enclosure(adapter=adapter_index, index=val)
            current_enc.raw["Device ID"] = val
        elif current_enc is not None:
            if key == "Logical ID":
                current_enc.raw["Logical ID"] = val
            elif key == "Numslots":
                current_enc.raw["Number of Slots"] = val
            elif key == "StartSlot":
                current_enc.raw["Start Slot"] = val
            else:
                current_enc.raw[key] = val
    if current_enc is not None and current_enc.raw:
        encs.append(current_enc)

    # Update Adapter physical device / VD counts now that we know.
    if adapters:
        adapters[0].flat["Physical Devices"] = str(len(pds))
        adapters[0].flat["Virtual Drives"] = str(len(lds))
        adapters[0].flat["BBU"] = "Absent"  # ircu HBAs never have BBU

    return adapters, pds, lds, encs


# --------------------------------------------------------------------------- #
# argv builders — only the subset ircu actually supports.
# --------------------------------------------------------------------------- #

def _ircu_target(pd: PhysicalDrive) -> str:
    """Format the 'enc:slot' pair ircu expects."""
    enc = pd.enclosure or "0"
    slot = pd.slot or pd.device_id or "0"
    return f"{enc}:{slot}"


def _build_locate_on(pd: PhysicalDrive) -> list[str]:
    return [str(pd.adapter), "LOCATE", _ircu_target(pd), "ON"]


def _build_locate_off(pd: PhysicalDrive) -> list[str]:
    return [str(pd.adapter), "LOCATE", _ircu_target(pd), "OFF"]


def _build_hsp_set(pd: PhysicalDrive) -> list[str]:
    return [str(pd.adapter), "HOTSPARE", "ADD", _ircu_target(pd)]


def _build_hsp_remove(pd: PhysicalDrive) -> list[str]:
    return [str(pd.adapter), "HOTSPARE", "DELETE", _ircu_target(pd)]


def _build_pd_create_r0(pd: PhysicalDrive) -> list[str]:
    # "CREATE N RAID0 MAX enc:slot" — RAID0 IR volume from one drive,
    # MAX uses the whole drive.
    return [str(pd.adapter), "CREATE", "0", "RAID0", "MAX", _ircu_target(pd), "noprompt"]


def _build_cfg_delete_all(adapter: int) -> list[str]:
    # DELETE removes ALL IR volumes; ircu prompts for 'YES' unless noprompt.
    return [str(adapter), "DELETE", "noprompt"]


def _build_rebuild_progress(pd: PhysicalDrive) -> list[str]:
    return [str(pd.adapter), "STATUS"]


IRCU_BUILDERS = {
    "locate_on":          _build_locate_on,
    "locate_off":         _build_locate_off,
    "hsp_set":            _build_hsp_set,
    "hsp_remove":         _build_hsp_remove,
    "pd_create_r0":       _build_pd_create_r0,
    "rebuild_progress":   _build_rebuild_progress,
    "cfg_delete_all_lds": _build_cfg_delete_all,
}


class IrcuBackend(Backend):
    name = "ircu"

    def __init__(
        self,
        *,
        binary: str | None = None,
        use_sudo: bool = True,
        fixtures_dir: str | None = None,
    ) -> None:
        resolved = binary or find_ircu_binary() or DEFAULT_SAS3IRCU_PATH
        self.binary = resolved
        self.runner = Runner(
            binary=resolved,
            use_sudo=use_sudo,
            fixtures_dir=fixtures_dir,
            fixture_lookup=_ircu_fixture,
        )

    # -- read path ------------------------------------------------------ #

    def _display(self) -> str:
        return self.runner.run(["0", "DISPLAY"]).stdout

    def adp_count(self) -> int:
        r = self.runner.run(["LIST"])
        return sum(1 for line in r.stdout.splitlines()
                   if re.search(r"^\s*\d+\s+SAS\d{3,4}", line))

    def adapters(self) -> list[Adapter]:
        adps, _, _, _ = parse_display(self._display())
        return adps

    def physical_drives(self) -> list[PhysicalDrive]:
        _, pds, _, _ = parse_display(self._display())
        return pds

    def logical_drives(self) -> list[LogicalDrive]:
        _, _, lds, _ = parse_display(self._display())
        return lds

    def enclosures(self) -> list[Enclosure]:
        _, _, _, encs = parse_display(self._display())
        return encs

    def bbu_statuses(self) -> list[BBUStatus]:
        # ircu HBAs have no BBU; surface a single "not present" record so the
        # BBU tab in the UI shows something meaningful.
        return [BBUStatus(adapter=0, present=False, error="ircu HBAs have no BBU")]

    # -- write path ----------------------------------------------------- #

    def supports(self, action_key: str) -> bool:
        return action_key in IRCU_BUILDERS

    def build_argv(self, action_key: str, target: Any) -> list[str]:
        builder = IRCU_BUILDERS.get(action_key)
        if builder is None:
            raise NotImplementedError(f"ircu backend has no builder for {action_key}")
        return builder(target)
