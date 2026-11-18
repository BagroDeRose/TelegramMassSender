"""app.ui.qr_code: the login dialog's self-contained QR encoder.

Checked against published reference values (the ISO/IEC 18004 worked
example's Reed-Solomon codewords, the format/version information tables,
capacities and alignment positions) and with an independent reader below
that unmasks the symbol and reads the payload back out. Separately,
during development every mask and versions 2-18 were decoded by jsQR, a
third-party decoder.
"""
from __future__ import annotations

import pytest

from app.ui import qr_code
from app.ui.qr_code import (
    QrCodeTooLongError,
    alignment_pattern_positions,
    encode,
    format_bits,
    mask_applies,
    num_data_codewords,
    reed_solomon_divisor,
    reed_solomon_remainder,
    version_bits,
)


def test_reed_solomon_matches_the_hello_world_1m_reference():
    # "HELLO WORLD", version 1-M (the standard worked example).
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    ecc = reed_solomon_remainder(data, reed_solomon_divisor(10))
    assert ecc == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


@pytest.mark.parametrize(
    "mask, expected",
    [
        (0, "101010000010010"),
        (1, "101000100100101"),
        (2, "101111001111100"),
        (3, "101101101001011"),
        (4, "100010111111001"),
        (5, "100000011001110"),
        (6, "100111110010111"),
        (7, "100101010100000"),
    ],
)
def test_format_bits_match_the_level_m_table(mask, expected):
    assert format(format_bits(mask), "015b") == expected


def test_version_bits_match_the_table():
    assert version_bits(7) == 0x07C94
    assert version_bits(40) == 0x28C69


def test_capacities_match_level_m():
    assert num_data_codewords(1) == 16
    assert num_data_codewords(4) == 64
    assert num_data_codewords(10) == 216
    assert num_data_codewords(40) == 2334


def test_alignment_positions():
    assert alignment_pattern_positions(1) == []
    assert alignment_pattern_positions(2) == [6, 18]
    assert alignment_pattern_positions(7) == [6, 22, 38]
    assert alignment_pattern_positions(32) == [6, 34, 60, 86, 112, 138]


def _read_back(modules) -> bytes:
    """An independent minimal reader: format bits -> mask, unmask, read
    the codewords in placement order, de-interleave, parse byte mode."""
    size = len(modules)
    version = (size - 17) // 4
    bits = 0
    for i in range(0, 6):
        bits |= modules[i][8] << i
    bits |= modules[7][8] << 6
    bits |= modules[8][8] << 7
    bits |= modules[8][7] << 8
    for i in range(9, 15):
        bits |= modules[8][14 - i] << i
    mask = next(m for m in range(8) if format_bits(m) == bits)

    # Rebuild which modules are function modules by encoding a dummy
    # symbol of the same version through the encoder's own layout.
    reserved = qr_code._Symbol(version)
    reserved.draw_function_patterns()

    stream = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vertical in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = (size - 1 - vertical) if upward else vertical
                if not reserved.is_function[y][x]:
                    stream.append(modules[y][x] ^ mask_applies(mask, x, y))
        right -= 2
    codewords = [int("".join("1" if b else "0" for b in stream[i:i + 8]), 2) for i in range(0, len(stream) - 7, 8)]

    num_blocks = qr_code._NUM_ERROR_CORRECTION_BLOCKS_M[version]
    ecc_len = qr_code._ECC_CODEWORDS_PER_BLOCK_M[version]
    raw = qr_code._num_raw_data_modules(version) // 8
    short_blocks = num_blocks - raw % num_blocks
    short_len = raw // num_blocks - ecc_len
    blocks = [[] for _ in range(num_blocks)]
    index = 0
    for i in range(short_len + 1):
        for b in range(num_blocks):
            if i == short_len and b < short_blocks:
                continue
            blocks[b].append(codewords[index])
            index += 1
    # The ECC codewords are interleaved the same way, column by column.
    block_ecc = [[] for _ in range(num_blocks)]
    for _ in range(ecc_len):
        for b in range(num_blocks):
            block_ecc[b].append(codewords[index])
            index += 1
    divisor = reed_solomon_divisor(ecc_len)
    data = []
    for b in range(num_blocks):
        assert reed_solomon_remainder(blocks[b], divisor) == block_ecc[b]
        data.extend(blocks[b])

    bit_string = "".join(format(byte, "08b") for byte in data)
    assert bit_string[:4] == "0100"
    count_bits = 8 if version <= 9 else 16
    length = int(bit_string[4:4 + count_bits], 2)
    start = 4 + count_bits
    return bytes(int(bit_string[start + 8 * i:start + 8 * i + 8], 2) for i in range(length))


@pytest.mark.parametrize(
    "text",
    [
        "tg://login?token=AQID",
        "tg://login?token=" + "x" * 43,
        "tg://login?token=" + "AbC-_9" * 20,
        "Привет",
        "y" * 300,
    ],
)
def test_round_trip(text):
    assert _read_back(encode(text)).decode("utf-8") == text


@pytest.mark.parametrize("mask", range(8))
def test_round_trip_with_every_mask(mask):
    text = "tg://login?token=" + "Q" * 43
    assert _read_back(encode(text, mask=mask)).decode("utf-8") == text


def test_a_login_url_is_a_small_symbol():
    # A real login token is 32 bytes: base64 43 chars + the scheme prefix.
    modules = encode("tg://login?token=" + "A" * 43)
    assert len(modules) == 4 * 4 + 17  # version 4


def test_finder_patterns_are_in_the_three_corners():
    modules = encode("hello")
    size = len(modules)
    for x0, y0 in ((0, 0), (size - 7, 0), (0, size - 7)):
        assert all(modules[y0][x0 + i] for i in range(7))  # top edge dark
        assert modules[y0 + 3][x0 + 3]  # centre dark
        assert not modules[y0 + 1][x0 + 1]  # ring light


def test_too_long_raises():
    with pytest.raises(QrCodeTooLongError):
        encode("z" * 3000)


def test_qr_pixmap_is_square_with_whole_modules(qapp):
    from app.ui.qr_code import QUIET_ZONE_MODULES, qr_pixmap

    text = "tg://login?token=" + "A" * 43
    pixmap = qr_pixmap(text, 240)
    count = len(encode(text)) + 2 * QUIET_ZONE_MODULES
    assert pixmap.width() == pixmap.height()
    assert pixmap.width() % count == 0
    assert pixmap.width() <= 240
