"""Codec tests pinned to frames actually captured from the Pro-D3 (serial
2417801136). If these change, the on-wire protocol assumptions changed."""

import pytest

from profoto import protocol as p


# --- scaling (verified on-device: byte 7 read 0.7 on the display) ---------
@pytest.mark.parametrize("fstop,byte", [(0.1, 1), (0.7, 7), (1.2, 12), (5.0, 50), (10.0, 100)])
def test_fstop_byte_roundtrip(fstop, byte):
    assert p.fstop_to_byte(fstop) == byte
    assert p.byte_to_fstop(byte) == fstop


@pytest.mark.parametrize("bad", [0.0, -1.0, 10.1, 50, True, "5"])
def test_fstop_out_of_range_rejected(bad):
    with pytest.raises(ValueError):
        p.fstop_to_byte(bad)


# --- frame builders -------------------------------------------------------
def test_prologue_frame():
    assert p.encode_prologue(0) == bytes([0x00, 0x1B, 0x00])
    assert p.encode_prologue(2) == bytes([0x02, 0x1B, 0x00])


def test_set_power_v2_frame():
    # The exact bytes the light ACK'd for 1.2 on head 0.
    assert p.encode_set_power_v2(1, 1.2, 0) == bytes([0x01, 0x23, 0x03, 0x00, 0x0C])


def test_counter_wraps_at_240():
    assert p.next_counter(0) == 1
    assert p.next_counter(238) == 239
    assert p.next_counter(239) == 0


# --- replies (real captured frames) ---------------------------------------
def test_classify_ack_nack():
    assert p.classify_reply(bytes.fromhex("72010001")) == ("ACK", 1)
    assert p.classify_reply(bytes.fromhex("38020001")) == ("NACK", 1)
    assert p.classify_reply(bytes.fromhex("007c000300")) is None  # a container


# --- AllSettingsV2 container parse (real dump frames) ---------------------
FRAME_A = bytes.fromhex(
    "007c00034a00310747000243b85f010d49000a323431373830313133360548000241360410000164030b000104110001060421030001"
)
FRAME_B = bytes.fromhex(
    "017c000494000011039300080309000103ac000003b20002031a0000037500000413000164041500015004230300070314001e05a400010700"
)


def test_parse_allsettings_serial():
    settings = p.parse_allsettings(FRAME_A)
    assert 73 in settings  # Serial field
    assert p.decode_string_value(settings[73]) == "2417801136"


def test_energy_from_settings_v2():
    settings = p.parse_allsettings(FRAME_B)
    assert 803 in settings  # MxEnergyV2
    # value 00 07 -> head 0, byte 7 -> 0.7 f-stops
    assert p.energy_from_settings(settings, head_id=0) == 0.7


def test_terminator_parses_empty():
    # An empty container frame (end-of-dump) yields no settings.
    assert p.parse_allsettings(bytes.fromhex("067c0000")) == {}
