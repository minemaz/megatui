"""Tests for storcli64 JSON backend."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import actions  # noqa: E402
from megatui.backends.storcli import (  # noqa: E402
    STORCLI_BUILDERS,
    StorcliBackend,
    parse_adp_all_info_json,
    parse_bbu_json,
    parse_encinfo_json,
    parse_ldinfo_json,
    parse_pdlist_json,
)
from megatui.parsers import LogicalDrive, PhysicalDrive  # noqa: E402


FIX = ROOT / "fixtures" / "storcli"


def read(name: str) -> str:
    return (FIX / name).read_text()


def test_parse_adp_all_info_real_9300_it_mode() -> None:
    adps = parse_adp_all_info_json(read("c0_show_all.json"))
    assert len(adps) == 1
    a = adps[0]
    assert a.product == "SAS9300-8i"
    assert "00deb7cf0" in a.serial.lower()        # 500605b00deb7cf0
    assert a.fw.startswith("15.")                  # 15.00.00.00
    assert a.bbu_present is False                  # 9300-8i has no BBU
    assert a.physical_devices == "1"               # one drive in fixture
    assert "mpt3sas" in a.get("Driver")
    assert "ROC Temperature" in a.flat


def test_parse_pdlist_real_9300_netapp() -> None:
    pds = parse_pdlist_json(read("c0_sall_show_all.json"))
    assert len(pds) == 1
    p = pds[0]
    assert p.adapter == 0
    assert p.slot == "0"
    assert p.device_id == "0"
    # storcli "UGood" must normalize to "Unconfigured(good)" so applicable
    # filters keep working.
    assert "Unconfigured(good)" in p.state
    assert "NETAPP" in p.inquiry
    assert "X477" in p.inquiry
    assert p.pd_type in {"SAS", "SAS HDD"}         # storcli Intf
    # Detailed merge: SAS Address(0) from Port Information table.
    assert p.raw.get("SAS Address(0)", "").startswith("0x")
    # Foreign State default → "None" so create_r0 isn't blocked spuriously.
    assert p.foreign_state == "None"


def test_parse_ldinfo_empty_on_hba() -> None:
    # 9300-8i in IT mode returns Failure / Un-supported → empty list.
    lds = parse_ldinfo_json(read("c0_vall_show_all.json"))
    assert lds == []


def test_parse_encinfo_no_enclosure() -> None:
    encs = parse_encinfo_json(read("c0_eall_show_all.json"))
    assert encs == []


def test_parse_bbu_unsupported() -> None:
    statuses = parse_bbu_json(read("c0_bbu_show_all.json"))
    assert len(statuses) == 1
    s = statuses[0]
    assert s.present is False
    assert s.error                                  # has description text


def test_storcli_path_construction_it_mode() -> None:
    """Direct-attach HBA drives use /cN/sN (no enclosure segment)."""
    pds = parse_pdlist_json(read("c0_sall_show_all.json"))
    p = pds[0]
    # locate ON path
    argv = STORCLI_BUILDERS["locate_on"](p)
    assert argv == ["/c0/s0", "start", "locate"], argv
    # make_good with force
    argv = STORCLI_BUILDERS["pd_make_good"](p)
    assert argv == ["/c0/s0", "set", "good", "force"], argv


def test_storcli_path_construction_enclosure() -> None:
    """When PD has an enclosure (RAID-mode card), path includes /eEID."""
    pd = PhysicalDrive(adapter=0)
    pd.raw["Enclosure Device ID"] = "252"
    pd.raw["Slot Number"] = "3"
    pd.raw["Device Id"] = "3"
    pd.raw["Firmware state"] = "Online"
    assert STORCLI_BUILDERS["locate_on"](pd) == ["/c0/e252/s3", "start", "locate"]
    assert STORCLI_BUILDERS["pd_offline"](pd) == ["/c0/e252/s3", "set", "offline"]


def test_storcli_action_visibility_for_netapp_drive() -> None:
    """Through StorcliBackend.supports(), only actions storcli knows surface.

    Critically, the NETAPP HDD in Unconfigured(good) state should show
    pd_make_bad / pd_clear / pd_create_r0 alongside locate.
    """
    pds = parse_pdlist_json(read("c0_sall_show_all.json"))
    p = pds[0]
    backend = StorcliBackend(fixtures_dir=str(FIX.parent), use_sudo=False)
    apps = actions.applicable_actions("pd", p, backend=backend)
    keys = {a.key for a in apps}
    assert "locate_on" in keys
    assert "locate_off" in keys
    assert "hsp_set" in keys                       # Unconfigured(good) → ok
    assert "pd_create_r0" in keys
    assert "pd_clear" in keys
    assert "pd_make_bad" in keys
    # Should NOT show — wrong state
    assert "rebuild_stop" not in keys
    assert "pd_online" not in keys
    assert "pd_make_good" not in keys              # already good


def test_storcli_ld_argv_shape() -> None:
    ld = LogicalDrive(adapter=0, ld_index="0")
    assert STORCLI_BUILDERS["ld_init_full"](ld) == ["/c0/v0", "start", "init", "full"]
    assert STORCLI_BUILDERS["ld_delete"](ld) == ["/c0/v0", "del", "force"]
    assert STORCLI_BUILDERS["ld_set_wb"](ld) == ["/c0/v0", "set", "wrcache=wb"]


def test_storcli_adapter_argv_shape() -> None:
    assert STORCLI_BUILDERS["pr_start"](0) == ["/c0", "start", "patrolread"]
    assert STORCLI_BUILDERS["alarm_silence"](0) == ["/c0", "set", "alarm=silence"]
    assert STORCLI_BUILDERS["bbu_learn"](0) == ["/c0/bbu", "start", "learn"]
    assert STORCLI_BUILDERS["cfg_clear"](0) == ["/c0", "delete", "config", "force"]


def test_storcli_backend_fixture_replay() -> None:
    """Running the backend in fixture mode wires every read path."""
    backend = StorcliBackend(fixtures_dir=str(FIX.parent), use_sudo=False)
    adps = backend.adapters()
    assert len(adps) == 1 and adps[0].product == "SAS9300-8i"
    pds = backend.physical_drives()
    assert len(pds) == 1 and "NETAPP" in pds[0].inquiry
    lds = backend.logical_drives()
    assert lds == []
    encs = backend.enclosures()
    assert encs == []
    bbu = backend.bbu_statuses()
    assert len(bbu) == 1 and bbu[0].present is False


if __name__ == "__main__":
    test_parse_adp_all_info_real_9300_it_mode()
    test_parse_pdlist_real_9300_netapp()
    test_parse_ldinfo_empty_on_hba()
    test_parse_encinfo_no_enclosure()
    test_parse_bbu_unsupported()
    test_storcli_path_construction_it_mode()
    test_storcli_path_construction_enclosure()
    test_storcli_action_visibility_for_netapp_drive()
    test_storcli_ld_argv_shape()
    test_storcli_adapter_argv_shape()
    test_storcli_backend_fixture_replay()
    print("all storcli tests OK")
