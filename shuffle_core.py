"""Lossless, in-memory shuffling for one-record-per-line text files.

Every source record moves to a different line number. Identical records (and
blank lines) can still *look* unchanged, because their contents are identical.
"""

from __future__ import annotations

import codecs
import re
from random import SystemRandom
from typing import TypeVar


MAX_LINES = 300_000
_SHUFFLE_ATTEMPTS = 16
_BYTE_NEWLINES = re.compile(rb"\r\n|\r|\n")
_TEXT_NEWLINES = re.compile(r"\r\n|\r|\n")
_Line = TypeVar("_Line", bytes, str)


class ShuffleError(ValueError):
    """A file cannot be safely shuffled as a list of text records."""


def _split_records(body: _Line) -> tuple[list[_Line], list[_Line]]:
    """Keep newline tokens in their original slots, separate from records."""
    pattern = _BYTE_NEWLINES if isinstance(body, bytes) else _TEXT_NEWLINES
    records: list[_Line] = []
    separators: list[_Line] = []
    cursor = 0
    for match in pattern.finditer(body):
        if len(records) >= MAX_LINES:
            raise ShuffleError(
                f"This file has too many lines. Split it into files of at most "
                f"{MAX_LINES:,} lines each."
            )
        records.append(body[cursor : match.start()])
        separators.append(match.group())
        cursor = match.end()

    # A final newline terminates the preceding record; it does not create an
    # extra empty record. Consecutive newline tokens do preserve blank records.
    if cursor < len(body):
        if len(records) >= MAX_LINES:
            raise ShuffleError(
                f"This file has too many lines. Split it into files of at most "
                f"{MAX_LINES:,} lines each."
            )
        records.append(body[cursor:])
    return records, separators


def _deranged_indices(size: int, allowed_last: set[int] | None = None) -> list[int]:
    """Use random permutations, with a bounded, always-valid fallback."""
    rng = SystemRandom()
    indices = list(range(size))
    for _ in range(_SHUFFLE_ATTEMPTS):
        rng.shuffle(indices)
        if (
            all(destination != source for destination, source in enumerate(indices))
            and (allowed_last is None or indices[-1] in allowed_last)
        ):
            return indices

    # Build one cycle, whose edge from the last position explicitly selects an
    # allowed source. One cycle cannot contain fixed points. This also avoids
    # an unbounded retry loop if almost all records are empty or the RNG is unlucky.
    candidates = [
        index for index in range(size - 1)
        if allowed_last is None or index in allowed_last
    ]
    first = candidates[rng.randrange(len(candidates))]
    middle = [index for index in range(size - 1) if index != first]
    rng.shuffle(middle)
    cycle = [size - 1, first, *middle]
    indices = list(range(size))
    for destination, source in zip(cycle, cycle[1:] + cycle[:1]):
        indices[destination] = source
    return indices


def shuffle_leads(data: bytes) -> tuple[bytes, int]:
    """Return shuffled file bytes and the total number of logical lines.

    Records keep their exact contents, including whitespace and duplicates.
    The first CRLF, LF, or CR separator determines the output newline style;
    files with mixed styles are normalized to that style. The presence or
    absence of a final newline is preserved. UTF-8 and UTF-16 BOMs are preserved;
    other inputs are treated as raw bytes so their encoding is not changed.
    At least two nonblank records are required. Blank records are retained and
    counted. No files are read or written by this function.
    """
    if not isinstance(data, bytes):
        raise TypeError("data must be bytes")

    if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        raise ShuffleError(
            "UTF-32 files are not supported. Save the file as UTF-8 or UTF-16 "
            "with a BOM."
        )

    bom = b""
    encoding = None
    if data.startswith(codecs.BOM_UTF16_LE):
        bom, encoding = codecs.BOM_UTF16_LE, "utf-16-le"
    elif data.startswith(codecs.BOM_UTF16_BE):
        bom, encoding = codecs.BOM_UTF16_BE, "utf-16-be"
    elif data.startswith(codecs.BOM_UTF8):
        bom = codecs.BOM_UTF8

    raw_body = data[len(bom) :]
    if encoding is not None:
        try:
            body = raw_body.decode(encoding, errors="surrogatepass")
        except UnicodeDecodeError as error:
            raise ShuffleError(
                "This UTF-16 file is incomplete. Save it again as UTF-8 or "
                "UTF-16 with a BOM."
            ) from error
    else:
        if b"\x00" in raw_body:
            raise ShuffleError(
                "This file contains NUL bytes and may be binary or UTF-16 "
                "without a BOM. Save it as UTF-8 or UTF-16 with a BOM."
            )
        body = raw_body

    records, separators = _split_records(body)
    if sum(bool(record.strip()) for record in records) < 2:
        raise ShuffleError("Please upload a file with at least two nonblank leads.")

    # A final empty record without a terminating newline would be indistinguishable
    # from a preceding final newline and would disappear when the file is read.
    # Keep that final slot nonempty, while retaining all empty records elsewhere.
    terminated = len(separators) == len(records)
    allowed_last = None if terminated else {
        index for index, record in enumerate(records) if record
    }
    order = _deranged_indices(len(records), allowed_last)

    # Mixed bare CR/LF tokens can merge into CRLF if an empty record moves between
    # them. A consistent separator avoids changing the logical number of records.
    separators = [separators[0]] * len(separators)
    parts = []
    for destination, source in enumerate(order):
        parts.append(records[source])
        if destination < len(separators):
            parts.append(separators[destination])
    shuffled = body[:0].join(parts)
    if encoding is not None:
        shuffled = shuffled.encode(encoding, errors="surrogatepass")
    return bom + shuffled, len(records)
