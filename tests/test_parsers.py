"""Smoke-test parsers against captured real-hardware fixtures."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import parsers  # noqa: E402

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
    test_bbu_present()
    print("all parser tests OK")
