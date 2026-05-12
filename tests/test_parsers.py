"""Smoke-test parsers against captured real-hardware fixtures."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import actions, parsers  # noqa: E402

FIX = ROOT / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text()


def test_pdlist_real_tape() -> None:
    pds = parsers.parse_pdlist(read("pdlist.txt"))
    assert len(pds) == 2, f"expected 2 PDs, got {len(pds)}"
    assert pds[0].device_id == "0"
    assert pds[1].device_id == "1"
    assert "Tape" in pds[0].pd_type
    assert "Ultrium" in pds[0].inquiry


def test_ldinfo_empty() -> None:
    lds = parsers.parse_ldinfo(read("ldinfo.txt"))
    assert lds == []


def test_adp_all_info() -> None:
    adps = parsers.parse_adp_all_info(read("adpinfo.txt"))
    assert len(adps) == 1
    a = adps[0]
    assert a.product == "LSI MegaRAID SAS 9261-8i"
    assert a.serial == "SV00000000"
    assert a.fw  # FW Version is present
    assert a.memory == "512MB"
    assert a.bbu_present is False  # BBU : Absent
    assert a.physical_devices == "3"


def test_encinfo() -> None:
    encs = parsers.parse_encinfo(read("encinfo.txt"))
    assert len(encs) == 1
    e = encs[0]
    assert e.index == "0"
    assert e.device_id == "252"
    assert e.slots == "8"
    assert e.status == "Normal"
    assert e.enc_type == "SGPIO"


def test_bbu_absent() -> None:
    statuses = parsers.parse_bbu(read("bbu.txt"))
    assert len(statuses) == 1
    s = statuses[0]
    assert s.present is False
    assert "not present" in s.error.lower()


def test_pdlist_hdd_synthetic() -> None:
    pds = parsers.parse_pdlist(read("pdlist_hdd.txt"))
    assert len(pds) == 5, f"expected 5 PDs, got {len(pds)}"
    assert pds[0].slot == "0"
    assert pds[0].state.startswith("Online")
    assert pds[0].size.startswith("1.818 TB")
    assert pds[0].media_errors == "0"
    assert pds[0].temperature.startswith("38C")
    assert pds[2].state == "Rebuild"
    assert pds[2].media_errors == "12"
    assert pds[3].state == "Failed"
    assert pds[3].media_errors == "47"
    assert pds[4].state.startswith("Hotspare")


def test_ldinfo_raid5() -> None:
    lds = parsers.parse_ldinfo(read("ldinfo_raid5.txt"))
    assert len(lds) == 2
    assert lds[0].ld_index == "0"
    assert lds[0].name == "data"
    assert "Primary-5" in lds[0].raid_level
    assert lds[0].size.startswith("5.456 TB")
    assert lds[0].state == "Optimal"
    assert lds[0].num_drives == "4"
    assert lds[1].state == "Degraded"


def test_pdlist_mixed_hdd_tape() -> None:
    """Regression: HDD record followed by tape entries must not swallow the tapes."""
    pds = parsers.parse_pdlist(read("pdlist_mixed_hdd_tape.txt"))
    assert len(pds) == 3, f"expected 3 PDs (1 HDD + 2 tapes), got {len(pds)}"
    assert pds[0].enclosure == "252"
    assert pds[0].slot == "2"
    assert pds[0].device_id == "2"
    assert "NETAPP" in pds[0].inquiry
    assert pds[0].state.startswith("Unconfigured")
    assert pds[1].enclosure == ""
    assert pds[1].device_id == "0"
    assert "Ultrium 4" in pds[1].inquiry
    assert "Tape" in pds[1].pd_type
    assert pds[2].device_id == "1"
    assert "Ultrium 5" in pds[2].inquiry


def test_pd_create_r0_action_gating() -> None:
    """Action 'pd_create_r0' must only surface for Unconfigured(good) PDs."""
    pds = parsers.parse_pdlist(read("pdlist_mixed_hdd_tape.txt"))
    # HDD slot 2 is Unconfigured(good) → should expose the create-RAID0 action
    hdd = next(p for p in pds if "NETAPP" in p.inquiry)
    pd_actions = actions.applicable_actions("pd", hdd)
    keys = {a.key for a in pd_actions}
    assert "pd_create_r0" in keys
    # Verify the produced argv is exactly the single-disk RAID0 form.
    create = next(a for a in pd_actions if a.key == "pd_create_r0")
    argv = create.build(hdd)
    assert argv == ["-CfgLdAdd", "-r0", "[252:2]", "-a0"], argv

    # An Online HDD (from synthetic fixture) must NOT see the create action.
    online_pds = parsers.parse_pdlist(read("pdlist_hdd.txt"))
    online = next(p for p in online_pds if p.state.startswith("Online"))
    keys = {a.key for a in actions.applicable_actions("pd", online)}
    assert "pd_create_r0" not in keys

    # Hotspare → also excluded.
    hsp = next(p for p in online_pds if p.state.startswith("Hotspare"))
    keys = {a.key for a in actions.applicable_actions("pd", hsp)}
    assert "pd_create_r0" not in keys


def _keys_for_state(state: str, *, foreign: str = "None") -> set[str]:
    pd = parsers.PhysicalDrive()
    pd.raw["Firmware state"] = state
    pd.raw["Foreign State"] = foreign
    pd.raw["Enclosure Device ID"] = "252"
    pd.raw["Slot Number"] = "0"
    return {a.key for a in actions.applicable_actions("pd", pd)}


def test_pd_action_gating_by_state() -> None:
    """Each PD action only appears for sensible state(s)."""
    online = _keys_for_state("Online, Spun Up")
    assert "pd_offline" in online
    assert "pd_make_bad" in online
    assert "pd_online" not in online           # already online
    assert "hsp_set" not in online             # not Unconfigured(good)
    assert "hsp_remove" not in online
    assert "pd_make_good" not in online        # nothing to recover
    assert "rebuild_start" not in online
    assert "rebuild_stop" not in online
    assert "pd_mark_missing" not in online
    assert "pd_clear" not in online            # safety: protect VD member
    assert "pd_create_r0" not in online

    ucfg_good = _keys_for_state("Unconfigured(good), Spun Up")
    assert "hsp_set" in ucfg_good
    assert "pd_create_r0" in ucfg_good
    assert "pd_clear" in ucfg_good
    assert "pd_make_bad" in ucfg_good
    assert "pd_offline" not in ucfg_good
    assert "pd_make_good" not in ucfg_good     # already good

    failed = _keys_for_state("Failed")
    assert "pd_make_good" in failed            # recovery
    assert "rebuild_start" in failed
    assert "pd_offline" not in failed
    assert "pd_make_bad" not in failed         # already failed
    assert "pd_clear" not in failed
    assert "hsp_set" not in failed
    assert "pd_create_r0" not in failed

    offline = _keys_for_state("Offline")
    assert "pd_online" in offline
    assert "pd_mark_missing" in offline
    assert "rebuild_start" in offline
    assert "pd_offline" not in offline
    assert "pd_make_bad" not in offline

    rebuild = _keys_for_state("Rebuild")
    assert "rebuild_stop" in rebuild
    assert "rebuild_start" not in rebuild
    assert "pd_clear" not in rebuild
    assert "pd_create_r0" not in rebuild

    hsp = _keys_for_state("Hotspare, Spun down")
    assert "hsp_remove" in hsp
    assert "hsp_set" not in hsp
    assert "pd_create_r0" not in hsp
    assert "pd_make_bad" in hsp                # demoting via Make Bad is legitimate

    foreign = _keys_for_state("Unconfigured(good), Spun Up", foreign="Foreign")
    assert "pd_make_good" in foreign           # has foreign → recoverable
    assert "pd_create_r0" not in foreign       # foreign present → block create
    assert "hsp_set" not in foreign            # has foreign → not eligible

    ucfg_bad = _keys_for_state("Unconfigured(bad)")
    assert "pd_make_good" in ucfg_bad
    assert "pd_clear" in ucfg_bad
    assert "rebuild_start" in ucfg_bad
    assert "pd_create_r0" not in ucfg_bad

    # Always-on actions: locate/progress
    for st in ("Online, Spun Up", "Failed", "Hotspare, Spun down", "Rebuild"):
        ks = _keys_for_state(st)
        assert "locate_on" in ks
        assert "locate_off" in ks
        assert "rebuild_progress" in ks
        assert "pd_clear_progress" in ks


def test_bbu_present() -> None:
    statuses = parsers.parse_bbu(read("bbu_present.txt"))
    assert len(statuses) == 1
    s = statuses[0]
    assert s.present is True
    assert s.adapter == 0
    assert s.battery_type == "BBU"
    assert s.voltage.startswith("4039")
    assert s.charge.startswith("100")


if __name__ == "__main__":
    test_pdlist_real_tape()
    test_ldinfo_empty()
    test_adp_all_info()
    test_encinfo()
    test_bbu_absent()
    test_pdlist_hdd_synthetic()
    test_ldinfo_raid5()
    test_pdlist_mixed_hdd_tape()
    test_pd_create_r0_action_gating()
    test_pd_action_gating_by_state()
    test_bbu_present()
    print("all parser tests OK")
