"""Conservative field extraction. Documents are data, never instructions."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import unicodedata

FIELDS = (
    "fullname", "date_of_birth", "bank", "address", "postcode", "phone",
    "email", "sort_code", "account_number",
)
MISSING = "Not provided"
MAX_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 10000
MAX_VALUE_CHARS = 10000


def label_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKC", value).lower())


ALIASES = {}
for target, labels in {
    "fullname": ("full name", "fullname", "name", "customer name", "client name"),
    "date_of_birth": ("date of birth", "dob", "birth date", "birthdate",
                      "date of birth dd/mm/yyyy", "dob dd/mm/yyyy", "date of birth yyyy-mm-dd"),
    "first": ("first name", "given name", "forename"),
    "last": ("last name", "surname", "family name"),
    "bank": ("bank", "bank name", "card bank", "bank institution"),
    "address": ("address", "full address", "postal address", "home address", "street address"),
    "county": ("county", "region"),
    "postcode": ("postcode", "post code", "postal code", "zip", "zip code"),
    "phone": ("phone", "telephone", "mobile", "phone number", "mobile number", "telephone number",
              "mobile telephone number", "contact number", "mobile phone"),
    "email": ("email", "email address", "e mail"),
    "sort_code": ("sort code", "sortcode", "bank sort code"),
    "account_number": ("account", "account number", "account no", "acc number", "acc no",
                       "bank account", "bank account number"),
}.items():
    for label in labels:
        ALIASES[label_key(label)] = target

# Labels/headings outside these sections are intentionally ignored.
SECTIONS = {
    "personalinformation": "personal", "personaldetails": "personal",
    "contactinformation": "personal", "contactdetails": "personal",
    "cardinformation": "card", "carddetails": "card",
    "accountinformation": "account", "accountdetails": "account",
    "bankinformation": "account", "bankdetails": "account",
    "moreinfo": "account", "moreinformation": "account",
}
ALLOWED = {
    "personal": {"fullname", "date_of_birth", "first", "last", "address", "county", "postcode", "phone", "email",
                 "bank", "sort_code", "account_number"},
    "card": {"bank", "sort_code", "account_number"},
    "account": {"bank", "sort_code", "account_number"},
    "ignore": set(),
}
POSTCODE = re.compile(r"\b(?:GIR\s*0AA|[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", re.I)


def undecorate(line: str) -> str:
    return line.strip().strip("+|=-─━ ").strip()


def is_record_heading(line: str) -> bool:
    # Anchored and punctuation-limited: the phrase inside a field value is not a boundary.
    return bool(re.fullmatch(r"[\s+|=\-─━]*personal\s+information[\s+|=\-─━]*", line, re.I))


def parse_text(text: str) -> list[dict[str, str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "").replace("\xa0", " ")
    if len(text) > MAX_BYTES:
        raise ValueError("Decoded document exceeds the 5 MB text limit.")
    blocks = []
    current = None
    for line in text.splitlines():
        if is_record_heading(line):
            if current is not None:
                blocks.append(current)
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)
    if not blocks:
        raise ValueError("No Personal Information record headings found.")
    if len(blocks) > MAX_RECORDS:
        raise ValueError("Too many records; split the input into smaller files.")

    rows = []
    for number, block in enumerate(blocks, 1):
        values = {}
        section = "personal"
        continuation = False

        def save(key, value):
            value = re.sub(r"\s+", " ", value).strip()
            if not value:
                return
            if len(value) > MAX_VALUE_CHARS:
                raise ValueError(f"Record {number}: field exceeds the length limit.")
            if key == "sort_code":
                digits = re.sub(r"[\s.\-]", "", value)
                if re.fullmatch(r"\d{6}", digits, flags=re.ASCII):
                    value = f"{digits[:2]}-{digits[2:4]}-{digits[4:]}"
                else:
                    raise ValueError(f"Record {number}: sort_code must contain six digits.")
            if key in values and values[key] != value:
                raise ValueError(f"Record {number}: conflicting values for {key}. Review that record.")
            values[key] = value

        for line in block:
            raw = line.strip()
            clean = undecorate(raw)
            # Any key/value line ends multiline-address continuation, even when unrecognised.
            if ":" in clean:
                continuation = False
                label, value = clean.split(":", 1)
                key = ALIASES.get(label_key(label))
                if key and key in ALLOWED[section]:
                    save(key, value)
                    continuation = key == "address" and bool(value.strip())
                continue
            if not clean:
                continuation = False
                continue
            heading = label_key(clean)
            if heading in SECTIONS:
                section = SECTIONS[heading]
                continuation = False
                continue
            # A decorated unfamiliar heading, e.g. PayPal, closes the recognised section.
            if raw.startswith("+") and not raw.startswith("|"):
                section = "ignore"
                continuation = False
                continue
            if continuation and raw.startswith("|"):
                values["address"] += ", " + clean
                if len(values["address"]) > MAX_VALUE_CHARS:
                    raise ValueError(f"Record {number}: field exceeds the length limit.")
            else:
                continuation = False

        if not values:
            continue
        if "fullname" not in values:
            name = " ".join(values.get(part, "") for part in ("first", "last")).strip()
            if name:
                values["fullname"] = name
        if "address" in values and "county" in values:
            if values["county"].casefold() not in values["address"].casefold():
                values["address"] += ", " + values["county"]
        if "postcode" not in values and "address" in values:
            match = POSTCODE.search(values["address"])
            if match:
                values["postcode"] = match.group()
        if "postcode" in values:
            values["postcode"] = values["postcode"].upper()
        rows.append({key: values.get(key, MISSING) for key in FIELDS})
    if not rows:
        raise ValueError("No recognised fields found under the record headings.")
    return rows


def decode_document(data: bytes, filename: str) -> str:
    if len(data) > MAX_BYTES:
        raise ValueError("File exceeds the 5 MB limit.")
    if not data.strip():
        raise ValueError("The file is empty.")
    suffix = Path(filename).suffix.lower()
    if suffix not in {".txt", ".rtf"}:
        raise ValueError("Upload a .txt or .rtf file.")
    if suffix == ".rtf":
        from striprtf.striprtf import rtf_to_text
        # Latin-1 is lossless for the raw byte stream. RTF escapes carry non-ASCII text.
        source = data.decode("latin-1").lstrip("\ufeff \r\n")
        if not source.startswith("{\\rtf"):
            raise ValueError("This .rtf file is not valid RTF. Export it again or use .txt.")
        if re.search(r"\\bin-?\d+", source):
            raise ValueError("RTF binary attachments are unsupported. Export the document as .txt.")
        depth = 0
        index = 0
        while index < len(source):
            char = source[index]
            if char == "\\":
                index += 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    raise ValueError("Malformed RTF. Export the document as plain text and try again.")
            index += 1
        if depth != 0:
            raise ValueError("Incomplete RTF. Export the document as plain text and try again.")
        try:
            return rtf_to_text(source, errors="strict")
        except (ValueError, LookupError, IndexError) as exc:
            raise ValueError("Could not read the RTF file. Export it as plain text and try again.") from exc
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("cp1252")
            except UnicodeDecodeError as exc:
                raise ValueError("Unsupported text encoding; save the file as UTF-8.") from exc
    if "\x00" in text:
        raise ValueError("This does not look like plain text. Save it as UTF-8.")
    return text


def clean_bytes(data: bytes, filename: str) -> list[dict[str, str]]:
    return parse_text(decode_document(data, filename))


def format_record(record: dict[str, str]) -> str:
    return "\n".join(f"{key}: {record.get(key) or MISSING}" for key in FIELDS)


def export_records(records: list[dict[str, str]]) -> str:
    return "\n\n".join(format_record(record) for record in records) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Clean a local .txt or .rtf assignment file.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("Choose a different output filename to preserve the original.")
    try:
        if args.input.stat().st_size > MAX_BYTES:
            raise ValueError("File exceeds the 5 MB limit.")
        records = clean_bytes(args.input.read_bytes(), args.input.name)
        args.output.write_text(export_records(records), encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Could not clean file: {exc}", file=sys.stderr)
        return 1
    print(f"Saved {len(records)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
