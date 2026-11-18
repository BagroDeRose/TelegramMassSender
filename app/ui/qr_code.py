"""QR code encoder for the login dialog's "Sign in with QR code" page.

Telegram's QR login hands the app a ``tg://login?token=...`` URL that the
user scans with Telegram on their phone (Settings > Devices > Link Desktop
Device). Qt has no QR generator, and this is the only QR code the app ever
draws, so this is a small self-contained encoder instead of a new
dependency: byte mode, error correction level M, versions 1-40, all eight
masks scored with the standard penalty rules. The structure follows the
QR Code specification (ISO/IEC 18004) as laid out in Project Nayuki's
reference implementation; tests/test_qr_code.py checks the Reed-Solomon
codewords, the format/version bits and a full decode round trip.

``encode()`` is pure (a square list of rows of booleans, True = dark);
``qr_pixmap()`` paints it with a quiet zone, always dark on light whatever
the theme -- phone cameras don't reliably read inverted codes.
"""
from __future__ import annotations

from typing import List, Sequence

Matrix = List[List[bool]]

# Error correction level M (the encoder only uses M: ~15 % recovery, enough
# for a code on a screen). Format bits for M are 0b00.
_ECL_M_FORMAT_BITS = 0

# Indexed by version (index 0 unused).
_ECC_CODEWORDS_PER_BLOCK_M = (
    -1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
    26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
)
_NUM_ERROR_CORRECTION_BLOCKS_M = (
    -1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16,
    17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49,
)

MIN_VERSION = 1
MAX_VERSION = 40

_PENALTY_N1 = 3
_PENALTY_N2 = 3
_PENALTY_N3 = 40
_PENALTY_N4 = 10

_FINDER_LIKE = (True, False, True, True, True, False, True)


class QrCodeTooLongError(ValueError):
    pass


# ---- Reed-Solomon over GF(2^8), polynomial 0x11D -------------------------------


def _gf_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def reed_solomon_divisor(degree: int) -> List[int]:
    """Generator polynomial coefficients, highest power first, the leading
    1 omitted -- the product of (x - a^i) for i in 0..degree-1."""
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_multiply(root, 0x02)
    return result


def reed_solomon_remainder(data: Sequence[int], divisor: Sequence[int]) -> List[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _gf_multiply(coefficient, factor)
    return result


# ---- capacity ------------------------------------------------------------------


def _num_raw_data_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        num_align = version // 7 + 2
        result -= (25 * num_align - 10) * num_align - 55
        if version >= 7:
            result -= 36
    return result


def num_data_codewords(version: int) -> int:
    return (
        _num_raw_data_modules(version) // 8
        - _ECC_CODEWORDS_PER_BLOCK_M[version] * _NUM_ERROR_CORRECTION_BLOCKS_M[version]
    )


def _char_count_bits(version: int) -> int:
    return 8 if version <= 9 else 16


def _choose_version(byte_count: int) -> int:
    for version in range(MIN_VERSION, MAX_VERSION + 1):
        needed = 4 + _char_count_bits(version) + 8 * byte_count
        if needed <= num_data_codewords(version) * 8:
            return version
    raise QrCodeTooLongError(f"{byte_count} bytes do not fit in a QR code")


def alignment_pattern_positions(version: int) -> List[int]:
    if version == 1:
        return []
    size = version * 4 + 17
    num_align = version // 7 + 2
    step = (version * 8 + num_align * 3 + 5) // (num_align * 4 - 4) * 2
    positions = [size - 7 - i * step for i in range(num_align - 1)] + [6]
    return list(reversed(positions))


# ---- data codewords --------------------------------------------------------------


def data_codewords(payload: bytes, version: int) -> List[int]:
    """Mode indicator, count, payload, terminator and pad bytes."""
    bits: List[int] = []

    def append(value: int, length: int) -> None:
        for i in reversed(range(length)):
            bits.append((value >> i) & 1)

    append(0b0100, 4)  # byte mode
    append(len(payload), _char_count_bits(version))
    for byte in payload:
        append(byte, 8)
    capacity = num_data_codewords(version) * 8
    append(0, min(4, capacity - len(bits)))
    append(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        append(pad, 8)
        pad ^= 0xEC ^ 0x11
    return [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]


def interleave_with_ecc(data: Sequence[int], version: int) -> List[int]:
    num_blocks = _NUM_ERROR_CORRECTION_BLOCKS_M[version]
    block_ecc_len = _ECC_CODEWORDS_PER_BLOCK_M[version]
    raw_codewords = _num_raw_data_modules(version) // 8
    num_short_blocks = num_blocks - raw_codewords % num_blocks
    short_block_len = raw_codewords // num_blocks
    divisor = reed_solomon_divisor(block_ecc_len)

    blocks: List[List[int]] = []
    k = 0
    for i in range(num_blocks):
        length = short_block_len - block_ecc_len + (0 if i < num_short_blocks else 1)
        block = list(data[k:k + length])
        k += length
        ecc = reed_solomon_remainder(block, divisor)
        if i < num_short_blocks:
            block.append(0)  # placeholder, skipped below
        blocks.append(block + ecc)

    result: List[int] = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_block_len - block_ecc_len or j >= num_short_blocks:
                result.append(block[i])
    return result


# ---- format / version bits ---------------------------------------------------------


def format_bits(mask: int) -> int:
    data = (_ECL_M_FORMAT_BITS << 3) | mask
    remainder = data
    for _ in range(10):
        remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
    return ((data << 10) | remainder) ^ 0x5412


def version_bits(version: int) -> int:
    remainder = version
    for _ in range(12):
        remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
    return (version << 12) | remainder


def _bit(value: int, index: int) -> bool:
    return ((value >> index) & 1) != 0


# ---- the symbol ----------------------------------------------------------------------


class _Symbol:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = version * 4 + 17
        self.modules: Matrix = [[False] * self.size for _ in range(self.size)]
        self.is_function: Matrix = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        self._draw_finder(3, 3)
        self._draw_finder(size - 4, 3)
        self._draw_finder(3, size - 4)
        positions = alignment_pattern_positions(self.version)
        count = len(positions)
        for i in range(count):
            for j in range(count):
                corner = (i == 0 and j == 0) or (i == 0 and j == count - 1) or (i == count - 1 and j == 0)
                if not corner:
                    self._draw_alignment(positions[i], positions[j])
        self.draw_format(0)  # reserves the area; redrawn once the mask is chosen
        self._draw_version()

    def _draw_finder(self, x: int, y: int) -> None:
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                xx, yy = x + dx, y + dy
                if 0 <= xx < self.size and 0 <= yy < self.size:
                    self.set_function(xx, yy, max(abs(dx), abs(dy)) not in (2, 4))

    def _draw_alignment(self, x: int, y: int) -> None:
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                self.set_function(x + dx, y + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(self, mask: int) -> None:
        bits = format_bits(mask)
        size = self.size
        for i in range(0, 6):
            self.set_function(8, i, _bit(bits, i))
        self.set_function(8, 7, _bit(bits, 6))
        self.set_function(8, 8, _bit(bits, 7))
        self.set_function(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, _bit(bits, i))
        for i in range(0, 8):
            self.set_function(size - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, _bit(bits, i))
        self.set_function(8, size - 8, True)  # the always-dark module

    def _draw_version(self) -> None:
        if self.version < 7:
            return
        bits = version_bits(self.version)
        for i in range(18):
            dark = _bit(bits, i)
            a = self.size - 11 + i % 3
            b = i // 3
            self.set_function(a, b, dark)
            self.set_function(b, a, dark)

    def draw_codewords(self, codewords: Sequence[int]) -> None:
        total_bits = len(codewords) * 8
        i = 0
        right = self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vertical in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = (self.size - 1 - vertical) if upward else vertical
                    if not self.is_function[y][x] and i < total_bits:
                        self.modules[y][x] = _bit(codewords[i >> 3], 7 - (i & 7))
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and mask_applies(mask, x, y):
                    self.modules[y][x] = not self.modules[y][x]


def mask_applies(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return x * y % 2 + x * y % 3 == 0
    if mask == 6:
        return (x * y % 2 + x * y % 3) % 2 == 0
    if mask == 7:
        return ((x + y) % 2 + x * y % 3) % 2 == 0
    raise ValueError(f"mask {mask}")


# ---- mask penalty ----------------------------------------------------------------------


def _line_penalty(line: Sequence[bool]) -> int:
    penalty = 0
    run_color = line[0]
    run_length = 1
    for module in line[1:]:
        if module == run_color:
            run_length += 1
            continue
        if run_length >= 5:
            penalty += _PENALTY_N1 + run_length - 5
        run_color = module
        run_length = 1
    if run_length >= 5:
        penalty += _PENALTY_N1 + run_length - 5
    # Finder-like 1:1:3:1:1 with four light modules on either side
    # (the quiet zone counts as light).
    padded = [False] * 4 + list(line) + [False] * 4
    for start in range(len(padded) - 6):
        if tuple(padded[start:start + 7]) != _FINDER_LIKE:
            continue
        before = padded[max(0, start - 4):start]
        after = padded[start + 7:start + 11]
        if (len(before) == 4 and not any(before)) or (len(after) == 4 and not any(after)):
            penalty += _PENALTY_N3
    return penalty


def penalty_score(modules: Matrix) -> int:
    size = len(modules)
    penalty = 0
    for row in modules:
        penalty += _line_penalty(row)
    for x in range(size):
        penalty += _line_penalty([modules[y][x] for y in range(size)])
    for y in range(size - 1):
        for x in range(size - 1):
            color = modules[y][x]
            if color == modules[y][x + 1] == modules[y + 1][x] == modules[y + 1][x + 1]:
                penalty += _PENALTY_N2
    dark = sum(sum(1 for module in row if module) for row in modules)
    total = size * size
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    penalty += max(0, k) * _PENALTY_N4
    return penalty


# ---- public API -------------------------------------------------------------------------


def encode(text: str, mask: int = -1) -> Matrix:
    """The QR symbol for ``text`` (UTF-8, byte mode, level M). ``mask`` -1
    picks the mask with the lowest penalty, as the specification asks."""
    payload = text.encode("utf-8")
    version = _choose_version(len(payload))
    codewords = interleave_with_ecc(data_codewords(payload, version), version)

    symbol = _Symbol(version)
    symbol.draw_function_patterns()
    symbol.draw_codewords(codewords)

    if mask == -1:
        best_mask, best_penalty = 0, None
        for candidate in range(8):
            symbol.apply_mask(candidate)
            symbol.draw_format(candidate)
            score = penalty_score(symbol.modules)
            if best_penalty is None or score < best_penalty:
                best_mask, best_penalty = candidate, score
            symbol.apply_mask(candidate)  # XOR again undoes it
        mask = best_mask
    symbol.apply_mask(mask)
    symbol.draw_format(mask)
    return symbol.modules


QUIET_ZONE_MODULES = 4


def qr_pixmap(text: str, target_px: int):
    """A QPixmap of ``text``'s QR code, no larger than ``target_px`` square,
    whole pixels per module so it stays sharp, with the quiet zone."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter, QPixmap

    from app.ui.theme import qcolor
    from app.ui.theme.tokens import QR_DARK, QR_LIGHT

    modules = encode(text)
    count = len(modules) + 2 * QUIET_ZONE_MODULES
    module_px = max(1, target_px // count)
    side = module_px * count
    pixmap = QPixmap(side, side)
    pixmap.fill(qcolor(QR_LIGHT))
    painter = QPainter(pixmap)
    try:
        dark = qcolor(QR_DARK)
        for y, row in enumerate(modules):
            for x, module in enumerate(row):
                if module:
                    painter.fillRect(
                        QRect(
                            (x + QUIET_ZONE_MODULES) * module_px,
                            (y + QUIET_ZONE_MODULES) * module_px,
                            module_px,
                            module_px,
                        ),
                        dark,
                    )
    finally:
        painter.end()
    return pixmap
