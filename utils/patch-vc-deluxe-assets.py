#!/usr/bin/env python3
"""Patch a local Vice City Deluxe asset overlay for reVC.

This script does not download or distribute game/mod assets. Run it after
copying a legally owned Vice City install to a run directory and overlaying
Vice City Deluxe assets on top of it.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


WHITE_ONLY_VEHICLES = ("sanchez", "pcj600", "faggio")


class GxtError(RuntimeError):
    pass


def align4(value: int) -> int:
    return (value + 3) & ~3


def read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pack_chunk(tag: bytes, payload: bytes) -> bytes:
    padding = b"\0" * (align4(len(payload)) - len(payload))
    return tag + struct.pack("<I", len(payload)) + payload + padding


def parse_tabl(payload: bytes) -> list[tuple[bytes, int]]:
    if len(payload) % 12:
        raise GxtError("TABL payload is not divisible by 12")

    entries = []
    for offset in range(0, len(payload), 12):
        name = payload[offset : offset + 8]
        value = read_u32(payload, offset + 8)
        entries.append((name, value))
    return entries


def pack_tabl(entries: list[tuple[bytes, int]]) -> bytes:
    out = bytearray()
    for name, value in entries:
        if len(name) != 8:
            raise GxtError("TABL names must be exactly 8 bytes")
        out.extend(name)
        out.extend(struct.pack("<I", value))
    return bytes(out)


def tabl_name(name: bytes) -> bytes:
    return name.rstrip(b"\0 ")


def parse_tkey(payload: bytes) -> list[tuple[bytes, int]]:
    if len(payload) % 12:
        raise GxtError("TKEY payload is not divisible by 12")

    entries = []
    for offset in range(0, len(payload), 12):
        value = read_u32(payload, offset)
        key = payload[offset + 4 : offset + 12]
        entries.append((key, value))
    return entries


def pack_tkey(entries: list[tuple[bytes, int]]) -> bytes:
    out = bytearray()
    for key, value in entries:
        if len(key) != 8:
            raise GxtError("TKEY keys must be exactly 8 bytes")
        out.extend(struct.pack("<I", value))
        out.extend(key)
    return bytes(out)


def printable_key(key: bytes) -> str:
    return key.rstrip(b"\0").decode("ascii", errors="replace")


class MainGxt:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self._parse()

    def _parse(self) -> None:
        data = self.data
        if data[:4] != b"TABL":
            raise GxtError(f"{self.path} does not start with TABL")

        self.tabl_size = read_u32(data, 4)
        self.tabl_start = 8
        self.tabl_end = self.tabl_start + self.tabl_size
        self.tabl_entries = parse_tabl(data[self.tabl_start : self.tabl_end])

        main_offsets = [value for name, value in self.tabl_entries if tabl_name(name) == b"MAIN"]
        if len(main_offsets) != 1:
            raise GxtError(f"{self.path} has no unique MAIN table")
        self.main_start = main_offsets[0]

        if self.main_start != align4(self.tabl_end):
            raise GxtError(f"{self.path} has an unexpected MAIN offset")

        if data[self.main_start : self.main_start + 4] != b"TKEY":
            raise GxtError(f"{self.path} MAIN does not start with TKEY")
        self.tkey_start = self.main_start + 8
        self.tkey_size = read_u32(data, self.main_start + 4)
        self.tkey_end = self.tkey_start + self.tkey_size
        self.tkey_payload = data[self.tkey_start : self.tkey_end]
        self.tkey_entries = parse_tkey(self.tkey_payload)

        self.tdat_chunk_start = align4(self.tkey_end)
        if data[self.tdat_chunk_start : self.tdat_chunk_start + 4] != b"TDAT":
            raise GxtError(f"{self.path} MAIN TKEY is not followed by TDAT")
        self.tdat_start = self.tdat_chunk_start + 8
        self.tdat_size = read_u32(data, self.tdat_chunk_start + 4)
        self.tdat_end = self.tdat_start + self.tdat_size
        self.tdat_payload = data[self.tdat_start : self.tdat_end]
        self.rest_start = align4(self.tdat_end)

    def string_for(self, value_offset: int) -> bytes:
        if value_offset < 0 or value_offset >= len(self.tdat_payload):
            raise GxtError(f"{self.path} has a TKEY offset outside TDAT")

        offset = value_offset
        while offset + 1 < len(self.tdat_payload):
            if self.tdat_payload[offset] == 0 and self.tdat_payload[offset + 1] == 0:
                return self.tdat_payload[value_offset : offset + 2]
            offset += 2

        raise GxtError(f"{self.path} has an unterminated TDAT string")


def merge_main_gxt(source_path: Path, target_path: Path, dry_run: bool) -> int:
    source = MainGxt(source_path)
    target = MainGxt(target_path)

    source_keys = {key: value for key, value in source.tkey_entries}
    target_keys = {key for key, _ in target.tkey_entries}
    missing = sorted(key for key in source_keys if key not in target_keys)
    if not missing:
        return 0

    new_tdat = bytearray(target.tdat_payload)
    new_tkey_entries = list(target.tkey_entries)

    for key in missing:
        value_offset = len(new_tdat)
        new_tdat.extend(source.string_for(source_keys[key]))
        new_tkey_entries.append((key, value_offset))

    new_tkey_entries.sort(key=lambda entry: entry[0])
    new_tkey = pack_tkey(new_tkey_entries)

    new_tdat_chunk_start = align4(target.main_start + 8 + len(new_tkey))
    new_rest_start = align4(new_tdat_chunk_start + 8 + len(new_tdat))
    rest_delta = new_rest_start - target.rest_start

    new_tabl_entries = []
    for name, value in target.tabl_entries:
        if tabl_name(name) != b"MAIN" and value >= target.rest_start:
            value += rest_delta
        new_tabl_entries.append((name, value))
    new_tabl = pack_tabl(new_tabl_entries)

    rebuilt = bytearray()
    rebuilt.extend(pack_chunk(b"TABL", new_tabl))
    rebuilt.extend(pack_chunk(b"TKEY", new_tkey))
    rebuilt.extend(pack_chunk(b"TDAT", bytes(new_tdat)))
    rebuilt.extend(target.data[target.rest_start :])

    if not dry_run:
        target_path.write_bytes(bytes(rebuilt))

    return len(missing)


def line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    return ""


def parse_car_section_lines(path: Path) -> dict[str, str]:
    in_car_section = False
    entries = {}
    for line in path.read_text(encoding="latin1").splitlines(keepends=True):
        body = line.split("#", 1)[0].strip()
        lower = body.lower()
        if lower == "car":
            in_car_section = True
            continue
        if lower == "end":
            in_car_section = False
            continue
        if not in_car_section or "," not in body:
            continue

        name = body.split(",", 1)[0].strip().lower()
        entries[name] = line.rstrip("\r\n")
    return entries


def car_colour_values(line: str) -> list[int]:
    body = line.split("#", 1)[0]
    if "," not in body:
        return []

    values = []
    for raw_value in body.split(",", 1)[1].split(","):
        raw_value = raw_value.strip()
        if not raw_value:
            continue
        try:
            values.append(int(raw_value, 10))
        except ValueError:
            return []
    return values


def patch_carcols(base_path: Path, target_path: Path, dry_run: bool) -> int:
    base_entries = parse_car_section_lines(base_path)
    target_lines = target_path.read_text(encoding="latin1").splitlines(keepends=True)

    in_car_section = False
    changed = 0
    out = []

    for line in target_lines:
        body = line.split("#", 1)[0].strip()
        lower = body.lower()
        if lower == "car":
            in_car_section = True
            out.append(line)
            continue
        if lower == "end":
            in_car_section = False
            out.append(line)
            continue

        if in_car_section and "," in body:
            name = body.split(",", 1)[0].strip().lower()
            values = car_colour_values(line)
            if (
                name in WHITE_ONLY_VEHICLES
                and name in base_entries
                and values
                and all(value == 1 for value in values)
            ):
                out.append(base_entries[name] + line_ending(line))
                changed += 1
                continue

        out.append(line)

    if changed and not dry_run:
        target_path.write_text("".join(out), encoding="latin1")

    return changed


def patch_gxt_files(base: Path, target: Path, dry_run: bool) -> int:
    total_missing = 0
    source_text = base / "TEXT"
    target_text = target / "TEXT"

    for target_gxt in sorted(target_text.glob("*.gxt")):
        source_gxt = source_text / target_gxt.name
        if not source_gxt.exists():
            continue
        count = merge_main_gxt(source_gxt, target_gxt, dry_run)
        if count:
            action = "would merge" if dry_run else "merged"
            print(f"{action} {count} missing text keys into {target_gxt}")
            total_missing += count

    return total_missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Patch a local Vice City Deluxe run directory for reVC."
    )
    parser.add_argument("--base", default="run-vc", help="base reVC run directory")
    parser.add_argument(
        "--target", default="run-vc-deluxe", help="Deluxe-overlay run directory"
    )
    parser.add_argument("--dry-run", action="store_true", help="report without writing")
    args = parser.parse_args()

    base = Path(args.base)
    target = Path(args.target)

    required = [
        base / "TEXT",
        target / "TEXT",
        base / "data" / "carcols.dat",
        target / "data" / "carcols.dat",
    ]
    missing = [path for path in required if not path.exists()]
    if missing:
        for path in missing:
            print(f"missing: {path}")
        return 1

    text_keys = patch_gxt_files(base, target, args.dry_run)
    car_lines = patch_carcols(
        base / "data" / "carcols.dat", target / "data" / "carcols.dat", args.dry_run
    )

    if car_lines:
        action = "would patch" if args.dry_run else "patched"
        names = ", ".join(WHITE_ONLY_VEHICLES)
        print(f"{action} {car_lines} white-only vehicle color entries ({names})")

    if not text_keys and not car_lines:
        print("Vice City Deluxe asset overlay already looks patched")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
