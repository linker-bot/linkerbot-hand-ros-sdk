"""SDK-backed validation and serialization of discovery adapter recipes."""

from pathlib import Path

import can
import pytest
from linkerbot_hand import ValidationError
from linkerbot_hand_ros.discovery_config import (
    channel_filter,
    discovery_settings,
    json_mapping,
    load_yaml,
    parse_discovery_config,
)


def test_all_backends_and_fd_recipes_round_trip_without_loading_library(tmp_path):
    timing = can.BitTimingFd.from_sample_point(
        f_clock=80_000_000,
        nom_bitrate=1_000_000,
        data_bitrate=5_000_000,
        nom_sample_point=80,
        data_sample_point=80,
    )
    values = {
        "backends": ["socketcan", "pcan", "slcan", "minicanfd"],
        "channels": ["can0", "pcan:PCAN_USBBUS1", "slcan:COM5", "minicanfd:0:1"],
        "l30_node_ids": [13],
        "o30_request_ids": [0x17],
        "pcan": {
            "channels": ["PCAN_USBBUS1"],
            "fd_timing": dict(timing),
            "probe_protocols": ["can_fd"],
        },
        "slcan": {"channels": ["COM5"], "bus_options": {"tty_baudrate": 115200}},
        "minicanfd": {
            "library_path": "lib/missing.so",
            "linux_channels": {"0": [1]},
            "config": {"config": 0},
        },
    }
    config = parse_discovery_config(values, base_dir=tmp_path)
    restored = parse_discovery_config(discovery_settings(config), base_dir=Path("/"))
    assert discovery_settings(restored) == discovery_settings(config)
    assert restored.minicanfd.library_path == str(tmp_path / "lib/missing.so")
    assert dict(restored.minicanfd.linux_channels) == {0: (1,)}
    assert restored.pcan.fd_timing.nom_bitrate == 1_000_000
    assert restored.slcan.bus_options["tty_baudrate"] == 115200
    assert restored.minicanfd.config.config == 0


@pytest.mark.parametrize(
    "settings",
    [
        {"backend": "socketcan"},
        {"channels": "can0"},
        {"channels": ["can0", "can0"]},
        {"channels": [""]},
        {"total_timeout_s": float("nan")},
        {"response_timeout_s": True},
        {"backends": ["custom"]},
        {"pcan": {"unknown": 1}},
        {"pcan": {"bus_options": {"channel": "x"}}},
        {"pcan": {"fd_timing": {"factory": "x"}}},
        {"slcan": {"probe_protocols": ["invalid"]}},
        {"minicanfd": {"linux_channels": {True: [0]}}},
        {"minicanfd": {"linux_channels": {0: [0], "0": [1]}}},
        {"minicanfd": {"linux_channels": {"4294967296": [0]}}},
        {"minicanfd": {"config": {"model": True}}},
    ],
)
def test_invalid_discovery_settings_are_rejected(settings):
    with pytest.raises(ValidationError):
        parse_discovery_config(settings)


def test_channels_csv_uses_report_names_and_sdk_validation():
    assert channel_filter("") is None
    assert channel_filter("can0, pcan:PCAN_USBBUS1") == ("can0", "pcan:PCAN_USBBUS1")
    for value in ("can0,", "can0,can0"):
        with pytest.raises(ValidationError):
            channel_filter(value)


@pytest.mark.parametrize(
    "text",
    [
        "channels: [can0]\nchannels: [can1]\n",
        "!!python/object/apply:os.system ['false']",
        "[can0]",
        "? [a, b]\n: value",
    ],
)
def test_yaml_rejects_duplicate_keys_executable_tags_and_invalid_roots(tmp_path, text):
    path = tmp_path / "settings.yaml"
    path.write_text(text)
    with pytest.raises(ValidationError):
        load_yaml(path)


def test_json_rejects_duplicate_keys():
    with pytest.raises(ValidationError, match="duplicate"):
        json_mapping('{"angles_hz": 1, "angles_hz": 2}')
