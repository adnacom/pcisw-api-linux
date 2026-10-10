"""Tests for the public Protocol API that run without hardware."""

import pytest
from unittest.mock import patch
from adnacom_monitor import Protocol
from adnacom_monitor.Protocol import DeviceDataReader, get_transceiver_channel_count

BDF = "0000:01:00.0"


class TestDeviceNotFound:
    """Every reader checks for the device before touching it."""

    @patch("adnacom_monitor.Protocol.os.path.exists", return_value=False)
    def test_read_device_info(self, _exists) -> None:
        with pytest.raises(FileNotFoundError, match="Device resource not found"):
            DeviceDataReader.read_device_info(BDF)

    @patch("adnacom_monitor.Protocol.os.path.exists", return_value=False)
    def test_read_cable_info(self, _exists) -> None:
        with pytest.raises(FileNotFoundError, match="Device resource not found"):
            DeviceDataReader.read_cable_info(BDF, 1)

    @patch("adnacom_monitor.Protocol.os.path.exists", return_value=False)
    def test_read_qsfp_info(self, _exists) -> None:
        with pytest.raises(FileNotFoundError, match="Device resource not found"):
            DeviceDataReader.read_qsfp_info(BDF, 0)


class TestIndexRange:
    """Out-of-range port and transceiver indices are rejected up front."""

    @patch("adnacom_monitor.Protocol.os.path.exists", return_value=True)
    def test_negative_port(self, _exists) -> None:
        with pytest.raises(ValueError):
            DeviceDataReader.read_cable_info(BDF, -1)

    @patch("adnacom_monitor.Protocol.os.path.exists", return_value=True)
    def test_qsfp_index_too_large(self, _exists) -> None:
        with pytest.raises(ValueError):
            DeviceDataReader.read_qsfp_info(BDF, 256)


@pytest.mark.parametrize("transceiver_type, channels", [(0, 4), (1, 1), (2, 2), (9, 4)])
def test_transceiver_channel_count(transceiver_type: int, channels: int) -> None:
    assert get_transceiver_channel_count(transceiver_type) == channels


def test_no_module_level_numeric_constants() -> None:
    """The compiled module exposes lookups and the API, not raw numbers."""
    numbers = [
        name
        for name, value in vars(Protocol).items()
        if not name.startswith("__")
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ]
    assert numbers == []
