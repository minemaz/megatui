"""Parse MegaCli64 textual output into structured dicts.

MegaCli output is line-oriented `Key : Value` with section headers and
blank-line separated records. We avoid being too strict — unknown keys
just fall through into a generic dict so the UI can show them in detail
views without losing data.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


_KV_RE = re.compile(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$")


def _kv(line: str) -> tuple[str, str] | None:
    m = _KV_RE.match(line)
    if not m:
        return None
    key = m.group(1).strip()
    val = m.group(2).strip()
    if not key:
        return None
    return key, val


# --------------------------------------------------------------------------- #
# Physical Drive list
# --------------------------------------------------------------------------- #

# Keys that indicate "this line starts a new PD record".
_PD_BOUNDARY_KEYS = ("Enclosure Device ID", "Device Id")


@dataclass
class PhysicalDrive:
    adapter: int = 0
    raw: dict[str, str] = field(default_factory=dict)

    # Convenience accessors -------------------------------------------------
    @property
    def device_id(self) -> str:
        return self.raw.get("Device Id", "")

    @property
    def enclosure(self) -> str:
        return self.raw.get("Enclosure Device ID", "")

    @property
    def slot(self) -> str:
        return self.raw.get("Slot Number", "")

    @property
    def pd_type(self) -> str:
        # Many firmwares print "PD Type", but tape-class devices may only have
        # "SCSI Device Type" / "Interface Type".
        return (
            self.raw.get("PD Type")
            or self.raw.get("SCSI Device Type")
            or self.raw.get("Interface Type")
            or ""
        )

    @property
    def media_type(self) -> str:
        return self.raw.get("Media Type", "")

    @property
    def state(self) -> str:
        # Firmware state is the canonical health field for HDDs.
        return self.raw.get("Firmware state") or self.raw.get("State", "")

    @property
    def size(self) -> str:
        return (
            self.raw.get("Coerced Size")
            or self.raw.get("Raw Size")
            or self.raw.get("Non Coerced Size")
            or ""
        )

    @property
    def media_errors(self) -> str:
        return self.raw.get("Media Error Count", "")

    @property
    def other_errors(self) -> str:
        return self.raw.get("Other Error Count", "")

    @property
    def predictive_failures(self) -> str:
        return self.raw.get("Predictive Failure Count", "")

    @property
    def temperature(self) -> str:
        return self.raw.get("Drive Temperature", "")

    @property
    def inquiry(self) -> str:
        return self.raw.get("Inquiry Data", "")

    @property
    def link_speed(self) -> str:
        return self.raw.get("Link Speed", "")

    @property
    def foreign_state(self) -> str:
        return self.raw.get("Foreign State", "")


def parse_pdlist(text: str) -> list[PhysicalDrive]:
    drives: list[PhysicalDrive] = []
    current: PhysicalDrive | None = None
    current_adapter = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if line.startswith("Adapter #"):
            try:
                current_adapter = int(line.split("#", 1)[1].strip())
            except ValueError:
                current_adapter = 0
            continue
        if line.startswith("Exit Code"):
            continue
        kv = _kv(line)
        if kv is None:
            continue
        key, val = kv
        if key in _PD_BOUNDARY_KEYS:
            # "Enclosure Device ID" always starts a new HDD-style record.
            # A bare "Device Id" line starts a new record whenever the
            # current record already has a Device Id — that signals we have
            # left the previous PD (HDD or tape) and entered a sparse tape
            # entry that lacks an Enclosure header. The HDD's own first
            # Device Id line is still absorbed because Device Id is not yet
            # present in current.raw at that point.
            start_new = False
            if key == "Enclosure Device ID":
                start_new = True
            elif key == "Device Id":
                if current is None or "Device Id" in current.raw:
                    start_new = True
            if start_new:
                if current is not None and current.raw:
                    drives.append(current)
                current = PhysicalDrive(adapter=current_adapter)
        if current is None:
            current = PhysicalDrive(adapter=current_adapter)
        current.raw[key] = val

    if current is not None and current.raw:
        drives.append(current)
    return drives


# --------------------------------------------------------------------------- #
# Logical Drive info
# --------------------------------------------------------------------------- #


@dataclass
class LogicalDrive:
    adapter: int = 0
    ld_index: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.raw.get("Name", "")

    @property
    def raid_level(self) -> str:
        return self.raw.get("RAID Level", "")

    @property
    def size(self) -> str:
        return self.raw.get("Size", "")

    @property
    def state(self) -> str:
        return self.raw.get("State", "")

    @property
    def num_drives(self) -> str:
        return self.raw.get("Number Of Drives", "") or self.raw.get(
            "Number Of Drives per span", ""
        )

    @property
    def strip_size(self) -> str:
        return self.raw.get("Strip Size", "")

    @property
    def write_cache(self) -> str:
        return self.raw.get("Current Cache Policy", "") or self.raw.get(
            "Default Cache Policy", ""
        )


_LD_HEADER_RE = re.compile(
    r"Virtual Drive\s*:\s*(\d+).*?(?:\(Target Id:\s*(\d+)\))?", re.IGNORECASE
)


def parse_ldinfo(text: str) -> list[LogicalDrive]:
    lds: list[LogicalDrive] = []
    current: LogicalDrive | None = None
    current_adapter = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m_adp = re.match(r"^Adapter\s+(\d+).*Virtual Drive Information", line)
        if m_adp:
            current_adapter = int(m_adp.group(1))
            continue
        if "No Virtual Drive Configured" in line:
            continue
        m_ld = _LD_HEADER_RE.search(line)
        if m_ld and "Virtual Drive" in line:
            if current is not None and current.raw:
                lds.append(current)
            current = LogicalDrive(adapter=current_adapter, ld_index=m_ld.group(1))
            continue
        kv = _kv(line)
        if kv is None or current is None:
            continue
        key, val = kv
        current.raw[key] = val

    if current is not None and current.raw:
        lds.append(current)
    return lds


# --------------------------------------------------------------------------- #
# Adapter info
# --------------------------------------------------------------------------- #


@dataclass
class Adapter:
    index: int = 0
    sections: dict[str, dict[str, str]] = field(default_factory=dict)
    flat: dict[str, str] = field(default_factory=dict)

    def get(self, key: str, default: str = "") -> str:
        return self.flat.get(key, default)

    @property
    def product(self) -> str:
        return self.get("Product Name")

    @property
    def serial(self) -> str:
        return self.get("Serial No")

    @property
    def fw(self) -> str:
        return self.get("FW Version") or self.get("FW Package Build")

    @property
    def memory(self) -> str:
        return self.get("Memory Size")

    @property
    def bbu_present(self) -> bool:
        return self.get("BBU").lower() in {"present", "yes", "true"}

    @property
    def virtual_drives(self) -> str:
        return self.get("Virtual Drives")

    @property
    def physical_devices(self) -> str:
        return self.get("Physical Devices")


def parse_adp_all_info(text: str) -> list[Adapter]:
    adapters: list[Adapter] = []
    current: Adapter | None = None
    current_section = "_root"
    pending_header: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m_adp = re.match(r"^Adapter\s*#(\d+)", line)
        if m_adp:
            if current is not None:
                adapters.append(current)
            current = Adapter(index=int(m_adp.group(1)))
            current_section = "_root"
            pending_header = None
            continue
        if line.startswith("Exit Code"):
            continue
        # Section header detection: "================" preceded by a heading
        if set(line.strip()) <= {"="} and len(line.strip()) >= 3 and pending_header:
            current_section = pending_header
            if current is not None and current_section not in current.sections:
                current.sections[current_section] = {}
            pending_header = None
            continue
        stripped = line.strip()
        if (
            stripped
            and ":" not in stripped
            and not stripped.startswith("=")
            and not stripped[0].isdigit()
            and len(stripped) < 60
        ):
            # Probable section heading — wait for the next "===" line.
            pending_header = stripped
            continue
        kv = _kv(line)
        if kv is None or current is None:
            continue
        key, val = kv
        # Section bucket
        sec = current.sections.setdefault(current_section, {})
        sec[key] = val
        # Flat lookup keeps the first-seen value for a key (most stable for
        # banner-style fields like Product Name).
        if key not in current.flat:
            current.flat[key] = val

    if current is not None:
        adapters.append(current)
    return adapters


# --------------------------------------------------------------------------- #
# Enclosure
# --------------------------------------------------------------------------- #


@dataclass
class Enclosure:
    adapter: int = 0
    index: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def device_id(self) -> str:
        return self.raw.get("Device ID", "")

    @property
    def slots(self) -> str:
        return self.raw.get("Number of Slots", "")

    @property
    def status(self) -> str:
        return self.raw.get("Status", "")

    @property
    def enc_type(self) -> str:
        return self.raw.get("Enclosure type", "")

    @property
    def num_drives(self) -> str:
        return self.raw.get("Number of Physical Drives", "")


def parse_encinfo(text: str) -> list[Enclosure]:
    encs: list[Enclosure] = []
    current: Enclosure | None = None
    current_adapter = 0

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m = re.search(r"Number of enclosures on adapter\s+(\d+)", line)
        if m:
            current_adapter = int(m.group(1))
            continue
        m_enc = re.match(r"\s*Enclosure\s+(\d+)\s*:?\s*$", line)
        if m_enc:
            if current is not None and current.raw:
                encs.append(current)
            current = Enclosure(adapter=current_adapter, index=m_enc.group(1))
            continue
        if line.startswith("Exit Code"):
            continue
        kv = _kv(line)
        if kv is None or current is None:
            continue
        key, val = kv
        current.raw[key] = val

    if current is not None and current.raw:
        encs.append(current)
    return encs


# --------------------------------------------------------------------------- #
# BBU
# --------------------------------------------------------------------------- #


@dataclass
class BBUStatus:
    adapter: int = 0
    present: bool = False
    error: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def battery_type(self) -> str:
        return self.raw.get("BatteryType", "") or self.raw.get("Battery Type", "")

    @property
    def voltage(self) -> str:
        return self.raw.get("Voltage", "")

    @property
    def current(self) -> str:
        return self.raw.get("Current", "")

    @property
    def temperature(self) -> str:
        return self.raw.get("Temperature", "")

    @property
    def state(self) -> str:
        return self.raw.get("Battery State", "") or self.raw.get(
            "Battery Replacement required", ""
        )

    @property
    def charge(self) -> str:
        return self.raw.get("Relative State of Charge", "") or self.raw.get(
            "Absolute State of charge", ""
        )


def parse_bbu(text: str) -> list[BBUStatus]:
    statuses: list[BBUStatus] = []
    current: BBUStatus | None = None
    in_error_block = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        m_adp = re.match(r"^BBU status for Adapter:\s*(\d+)", line)
        if m_adp:
            if current is not None:
                statuses.append(current)
            current = BBUStatus(adapter=int(m_adp.group(1)), present=True)
            in_error_block = False
            continue
        m_fail = re.match(r"^Adapter\s+(\d+):\s+Get BBU Status Failed", line)
        if m_fail:
            if current is not None:
                statuses.append(current)
            current = BBUStatus(adapter=int(m_fail.group(1)), present=False)
            in_error_block = False
            continue
        if line.startswith("Exit Code"):
            in_error_block = False
            continue
        if line.startswith("FW error description"):
            in_error_block = True
            # The description text usually arrives on the following lines.
            _, _, rhs = line.partition(":")
            rhs = rhs.strip()
            if rhs and current is not None:
                current.error = (current.error + " " + rhs).strip()
            continue
        if in_error_block and current is not None and not current.present:
            stripped = line.strip()
            if stripped:
                current.error = (current.error + " " + stripped).strip()
            continue
        kv = _kv(line)
        if kv is None:
            continue
        key, val = kv
        if current is None:
            current = BBUStatus(adapter=0, present=True)
        # Top-level battery fields (Voltage, Temperature, Current) appear
        # before the BBU Firmware Status block which reuses the same names
        # with summary values like "OK". First-seen wins so headline values
        # are preserved.
        current.raw.setdefault(key, val)

    if current is not None:
        statuses.append(current)
    return statuses
