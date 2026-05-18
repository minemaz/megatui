"""Tests for sas2ircu / sas3ircu backend."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import actions  # noqa: E402
from megatui.backends.ircu import (  # noqa: E402
    IRCU_BUILDERS,
    IrcuBackend,
    parse_display,
)
from megatui.parsers import LogicalDrive, PhysicalDrive  # noqa: E402


FIX = ROOT / "fixtures" / "ircu"


def read(name: str) -> str:
    return (FIX / name).read_text()


def test_parse_display_9300_real_it_mode() -> None:
    """Real capture from epyc-7k62 (9300-8i + NETAPP X477 in IT-mode FW)."""
    adps, pds, lds, encs = parse_display(read("display.txt"))
    assert len(adps) == 1
    a = adps[0]
    assert a.product == "SAS3008"
    assert a.fw == "15.00.00.00"
    assert a.bbu_present is False                  # ircu HBAs have no BBU
    assert a.physical_devices == "1"
    # IT-mode firmware reports RAID Support: No.
    assert a.get("RAID Support") == "No"

    assert len(pds) == 1
    p = pds[0]
    assert p.enclosure == "1"
    assert p.slot == "0"
    # AVL → "Available" (NOT Unconfigured(good)) so create/HSP actions are
    # hidden naturally on IT-mode firmware that can't honor them.
    assert "Available" in p.state
    assert "Unconfigured(good)" not in p.state
    assert "NETAPP" in p.inquiry
    assert "X477" in p.inquiry
    # NETAPP X477 in its 520-byte sector format reports unknown size.
    assert "???" in p.size

    # No IR volumes — the controller can't host them in IT mode.
    assert lds == []

    # Just one enclosure (the controller's own SES) on this direct-attach setup.
    assert len(encs) == 1
    assert encs[0].index == "1"


def test_parse_display_with_ir_volume_raid1() -> None:
    adps, pds, lds, encs = parse_display(read("display_with_ir_volume.txt"))
    assert len(adps) == 1
    assert adps[0].virtual_drives == "1"
    assert adps[0].physical_devices == "3"

    # IR volume RAID1, two members + one hot spare.
    assert len(lds) == 1
    ld = lds[0]
    assert ld.ld_index == "1"
    assert "RAID1" in ld.raid_level
    assert "1907200" in ld.size
    # OKY → Optimal so applicable predicates work.
    assert "Optimal" in ld.state

    # Hot spare PD state should normalize to "Hotspare".
    hsp = next(p for p in pds if "NETAPP" in p.inquiry)
    assert "Hotspare" in hsp.state

    # The two RAID1 members are reported as "Optimal (OPT)" → normalises to
    # "Online" so the action filter treats them like working VD members.
    members = [p for p in pds if "SEAGATE" in p.inquiry]
    assert len(members) == 2
    for m in members:
        assert "Online" in m.state


def test_ircu_argv_shape() -> None:
    pd = PhysicalDrive(adapter=0)
    pd.raw["Enclosure Device ID"] = "2"
    pd.raw["Slot Number"] = "0"
    pd.raw["Device Id"] = "0"
    pd.raw["Firmware state"] = "Unconfigured(good)"
    pd.raw["Foreign State"] = "None"

    assert IRCU_BUILDERS["locate_on"](pd) == ["0", "LOCATE", "2:0", "ON"]
    assert IRCU_BUILDERS["locate_off"](pd) == ["0", "LOCATE", "2:0", "OFF"]
    assert IRCU_BUILDERS["hsp_set"](pd) == ["0", "HOTSPARE", "ADD", "2:0"]
    assert IRCU_BUILDERS["hsp_remove"](pd) == ["0", "HOTSPARE", "DELETE", "2:0"]
    assert IRCU_BUILDERS["pd_create_r0"](pd) == [
        "0", "CREATE", "0", "RAID0", "MAX", "2:0", "noprompt"
    ]
    assert IRCU_BUILDERS["rebuild_progress"](pd) == ["0", "STATUS"]
    assert IRCU_BUILDERS["cfg_delete_all_lds"](0) == ["0", "DELETE", "noprompt"]


def test_ircu_supports_only_subset() -> None:
    """ircu's capability ceiling is much lower than storcli/MegaCli."""
    b = IrcuBackend(fixtures_dir=str(FIX), use_sudo=False, binary="/bin/true")
    # supported
    for key in ("locate_on", "locate_off", "hsp_set", "hsp_remove",
                "pd_create_r0", "rebuild_progress", "cfg_delete_all_lds"):
        assert b.supports(key), key
    # NOT supported (ircu lacks these operations entirely)
    for key in ("pd_make_good", "pd_make_bad", "pd_offline", "pd_online",
                "pd_clear", "rebuild_start", "rebuild_stop",
                "ld_init_start", "ld_cc_start", "ld_set_wb", "pr_start",
                "bbu_learn", "cfg_clear"):
        assert not b.supports(key), key


def test_ircu_action_visibility_it_mode() -> None:
    """On IT-mode FW, only locate/status surface — RAID-managing actions hidden."""
    _, pds, _, _ = parse_display(read("display.txt"))
    p = pds[0]
    backend = IrcuBackend(fixtures_dir=str(FIX), use_sudo=False, binary="/bin/true")
    keys = {a.key for a in actions.applicable_actions("pd", p, backend=backend)}
    # Should appear (state-agnostic)
    assert "locate_on" in keys
    assert "locate_off" in keys
    assert "rebuild_progress" in keys
    # Should NOT appear: drive is "Available", not Unconfigured(good)
    assert "hsp_set" not in keys
    assert "pd_create_r0" not in keys
    # Should NOT appear: ircu lacks these operations entirely
    assert "pd_make_bad" not in keys
    assert "pd_make_good" not in keys
    assert "pd_clear" not in keys
    assert "pd_offline" not in keys


def test_ircu_action_visibility_ir_mode() -> None:
    """On IR-mode FW with healthy drives in RDY, create-VD / HSP-add surface."""
    _, pds, _, _ = parse_display(read("display_with_ir_volume.txt"))
    # The NETAPP HDD in this synthetic fixture is in Hotspare state.
    hsp = next(p for p in pds if "NETAPP" in p.inquiry)
    backend = IrcuBackend(fixtures_dir=str(FIX), use_sudo=False, binary="/bin/true")
    keys = {a.key for a in actions.applicable_actions("pd", hsp, backend=backend)}
    assert "hsp_remove" in keys                  # currently a hot spare
    assert "hsp_set" not in keys                 # already one
    assert "pd_create_r0" not in keys            # already in use


def test_ircu_backend_fixture_replay() -> None:
    backend = IrcuBackend(fixtures_dir=str(FIX), use_sudo=False, binary="/bin/true")
    adps = backend.adapters()
    assert len(adps) == 1 and adps[0].product == "SAS3008"
    pds = backend.physical_drives()
    assert len(pds) == 1 and "NETAPP" in pds[0].inquiry
    lds = backend.logical_drives()
    assert lds == []
    encs = backend.enclosures()
    assert len(encs) == 1                          # real capture has one
    bbu = backend.bbu_statuses()
    assert bbu and bbu[0].present is False


if __name__ == "__main__":
    test_parse_display_9300_real_it_mode()
    test_parse_display_with_ir_volume_raid1()
    test_ircu_argv_shape()
    test_ircu_supports_only_subset()
    test_ircu_action_visibility_it_mode()
    test_ircu_action_visibility_ir_mode()
    test_ircu_backend_fixture_replay()
    print("all ircu tests OK")
