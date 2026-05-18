"""Tests for the sg_format integration (pd_reformat_512 action)."""
import pathlib
import sys
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from megatui import actions  # noqa: E402
from megatui.backends.megacli import MegaCliBackend  # noqa: E402
from megatui.backends.storcli import StorcliBackend  # noqa: E402
from megatui.backends.ircu import IrcuBackend  # noqa: E402
from megatui.parsers import PhysicalDrive  # noqa: E402
from megatui.sg_util import (  # noqa: E402
    SgPathNotFound,
    _normalize_sas,
    find_sg_path,
    sg_format_argv,
)


# Sample lsscsi -tg output from epyc-7k62 (post-format)
_LSSCSI_OUTPUT = (
    "[16:0:0:0]   disk    sas:0x500003983838705d                          /dev/sda   /dev/sg0\n"
    "[0:0:0:0]    disk    usb:                                            /dev/sdc   /dev/sg2\n"
    "[1:0:0:0]    disk    sata:0x12340000abcd                              /dev/sdb   /dev/sg1\n"
)


def _make_pd(sas: str = "0x500003983838705d") -> PhysicalDrive:
    pd = PhysicalDrive(adapter=0)
    pd.raw["SAS Address(0)"] = sas
    pd.raw["Enclosure Device ID"] = ""
    pd.raw["Slot Number"] = "0"
    pd.raw["Device Id"] = "0"
    pd.raw["Firmware state"] = "Unconfigured(good)"
    pd.raw["Foreign State"] = "None"
    pd.raw["Inquiry Data"] = "NETAPP X477"
    return pd


def test_normalize_sas() -> None:
    assert _normalize_sas("0x500003983838705d") == "500003983838705d"
    assert _normalize_sas("5000039838387035") == "5000039838387035"
    assert _normalize_sas("5000039-8-3838-7035") == "500003983838705"[:14] + "35"  # dashes stripped
    assert _normalize_sas("0X500605B00DEB7CF0") == "500605b00deb7cf0"
    assert _normalize_sas("") == ""


def test_sg_format_argv_default() -> None:
    argv = sg_format_argv("/dev/sg0")
    assert argv == [
        "--format", "--size=512", "--fmtpinfo=0",
        "--early", "--quick", "/dev/sg0",
    ]


def test_sg_format_argv_no_early_no_quick() -> None:
    argv = sg_format_argv("/dev/sg9", early=False, quick=False)
    assert "--early" not in argv
    assert "--quick" not in argv
    assert argv[-1] == "/dev/sg9"


def test_find_sg_path_match_by_sas_address() -> None:
    pd = _make_pd("0x500003983838705d")
    with patch("megatui.sg_util.subprocess.run") as mocked:
        mocked.return_value.stdout = _LSSCSI_OUTPUT
        assert find_sg_path(pd) == "/dev/sg0"


def test_find_sg_path_no_match() -> None:
    pd = _make_pd("0xdeadbeefcafebabe")
    with patch("megatui.sg_util.subprocess.run") as mocked:
        mocked.return_value.stdout = _LSSCSI_OUTPUT
        assert find_sg_path(pd) is None


def test_find_sg_path_no_lsscsi() -> None:
    pd = _make_pd()
    with patch("megatui.sg_util.subprocess.run", side_effect=FileNotFoundError):
        assert find_sg_path(pd) is None


def test_pd_reformat_512_in_action_catalogue() -> None:
    """The action exists and has the expected typed-phrase confirmation."""
    a = next(x for x in actions.PD_ACTIONS if x.key == "pd_reformat_512")
    assert a.danger == "catastrophic"
    assert a.confirm_phrase == "REFORMAT-512"
    assert a.applicable is not None


def test_supports_pd_reformat_512_across_backends() -> None:
    """All three backends acknowledge pd_reformat_512 when sg_format is
    installed and the drive has a SAS address."""
    pd = _make_pd()
    # Pretend sg_format is installed.
    with patch("megatui.backends.base.sg_format_installed", return_value=True):
        for B in (MegaCliBackend, StorcliBackend, IrcuBackend):
            b = B(fixtures_dir="fixtures", use_sudo=False)
            assert b.supports("pd_reformat_512", pd), B.__name__
            assert b.tool_for("pd_reformat_512") == "/usr/bin/sg_format"


def test_supports_pd_reformat_512_when_sg_format_missing() -> None:
    pd = _make_pd()
    with patch("megatui.backends.base.sg_format_installed", return_value=False):
        b = StorcliBackend(use_sudo=False, fixtures_dir="fixtures")
        assert not b.supports("pd_reformat_512", pd)


def test_supports_pd_reformat_512_drive_without_sas() -> None:
    """Tape drives etc. with no SAS address shouldn't see the action."""
    pd = PhysicalDrive(adapter=0)
    pd.raw["Inquiry Data"] = "HP Ultrium 5"
    pd.raw["PD Type"] = "Tape"
    with patch("megatui.backends.base.sg_format_installed", return_value=True):
        b = StorcliBackend(use_sudo=False, fixtures_dir="fixtures")
        assert not b.supports("pd_reformat_512", pd)


def test_build_argv_resolves_sg_path() -> None:
    pd = _make_pd("0x500003983838705d")
    b = StorcliBackend(use_sudo=False, fixtures_dir="fixtures")
    with patch("megatui.sg_util.subprocess.run") as mocked:
        mocked.return_value.stdout = _LSSCSI_OUTPUT
        argv = b.build_argv("pd_reformat_512", pd)
    assert argv == [
        "--format", "--size=512", "--fmtpinfo=0",
        "--early", "--quick", "/dev/sg0",
    ]


def test_build_argv_raises_when_drive_not_visible() -> None:
    """When the drive can't be found in lsscsi (typical for VD members
    behind non-JBOD MegaRAID), build_argv must raise — caller surfaces
    the error in the confirmation modal."""
    pd = _make_pd("0xdeadbeefdeadbeef")
    b = MegaCliBackend(use_sudo=False, fixtures_dir="fixtures")
    with patch("megatui.sg_util.subprocess.run") as mocked:
        mocked.return_value.stdout = _LSSCSI_OUTPUT
        try:
            b.build_argv("pd_reformat_512", pd)
        except SgPathNotFound as e:
            assert "/dev/sg" in str(e)
        else:
            assert False, "expected SgPathNotFound"


def test_applicable_actions_filters_pd_reformat_512() -> None:
    """The action menu surfaces pd_reformat_512 for drives with SAS address
    AND a working tool path AND sg_format installed."""
    pd = _make_pd()
    with patch("megatui.backends.base.sg_format_installed", return_value=True):
        b = StorcliBackend(use_sudo=False, fixtures_dir="fixtures")
        # populate RAID-capable cache so other RAID-only actions don't appear
        b._raid_capable_adapters = set()
        keys = {a.key for a in actions.applicable_actions("pd", pd, backend=b)}
        assert "pd_reformat_512" in keys


if __name__ == "__main__":
    test_normalize_sas()
    test_sg_format_argv_default()
    test_sg_format_argv_no_early_no_quick()
    test_find_sg_path_match_by_sas_address()
    test_find_sg_path_no_match()
    test_find_sg_path_no_lsscsi()
    test_pd_reformat_512_in_action_catalogue()
    test_supports_pd_reformat_512_across_backends()
    test_supports_pd_reformat_512_when_sg_format_missing()
    test_supports_pd_reformat_512_drive_without_sas()
    test_build_argv_resolves_sg_path()
    test_build_argv_raises_when_drive_not_visible()
    test_applicable_actions_filters_pd_reformat_512()
    print("all sg_format tests OK")
