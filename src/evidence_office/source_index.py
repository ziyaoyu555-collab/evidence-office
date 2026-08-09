"""Deterministic, dependency-free source indexing for common Office inputs."""

from __future__ import annotations

import csv
import hashlib
import os
import posixpath
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from .model import ProjectManifest, SourceSnapshot
from .storage import read_json


_CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MAX_XML_MEMBER_BYTES = 64 * 1024 * 1024
_MAX_XML_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_SOURCE_ANCHORS = 250_000
_MAX_VALUE_ANCHOR_CHARS = 512
_MAX_TEXT_SOURCE_BYTES = 64 * 1024 * 1024
_TEXT_SOURCE_SUFFIXES = frozenset({".csv", ".json", ".md", ".txt", ".m"})


class _SourceLimitError(ValueError):
    pass


_OFFICE_ERRORS = (
    KeyError,
    ElementTree.ParseError,
    OSError,
    RuntimeError,
    ValueError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_members(archive: zipfile.ZipFile) -> set[str]:
    entries = archive.infolist()
    if len(entries) > _MAX_ARCHIVE_ENTRIES:
        raise _SourceLimitError("Office archive contains too many entries.")
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("Office archive contains duplicate member names.")
    xml_entries = [entry for entry in entries if entry.filename.endswith((".xml", ".rels"))]
    if sum(entry.file_size for entry in xml_entries) > _MAX_XML_TOTAL_BYTES:
        raise _SourceLimitError("Office archive XML exceeds the indexing budget.")
    return set(names)


def _read_xml(archive: zipfile.ZipFile, member: str) -> ElementTree.Element:
    entry = archive.getinfo(member)
    if entry.file_size > _MAX_XML_MEMBER_BYTES:
        raise _SourceLimitError(f"Office XML member is too large: {member}")
    content = archive.read(entry)
    if b"<!DOCTYPE" in content or b"<!ENTITY" in content:
        raise ValueError("Office XML document types and entities are not permitted.")
    return ElementTree.fromstring(content)


def _zip_xml(path: Path, member: str) -> ElementTree.Element | None:
    try:
        with zipfile.ZipFile(path) as archive:
            _archive_members(archive)
            return _read_xml(archive, member)
    except _OFFICE_ERRORS:
        return None


def _relationship_targets(archive: zipfile.ZipFile, member: str) -> dict[str, str]:
    root = _read_xml(archive, member)
    targets: dict[str, str] = {}
    for relation in root.findall(f"{{{_PACKAGE_REL_NS}}}Relationship"):
        relation_id = relation.attrib.get("Id", "")
        if not relation_id or relation_id in targets:
            raise ValueError("Office relationships contain a missing or duplicate id.")
        targets[relation_id] = relation.attrib.get("Target", "")
    return targets


def _archive_target(base: str, target: str) -> str:
    target = target.replace("\\", "/")
    if not target:
        raise ValueError("Office relationship target is empty.")
    normalized = posixpath.normpath(
        target.lstrip("/") if target.startswith("/") else posixpath.join(base, target)
    )
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("Office relationship target escapes the archive root.")
    return normalized


def _check_anchor_budget(anchors: set[str]) -> None:
    if len(anchors) > _MAX_SOURCE_ANCHORS:
        raise _SourceLimitError("Source contains too many indexable anchors.")


def _base_anchors(path: Path) -> set[str]:
    return {"file", f"file:{path.name}"}


def _unavailable(path: Path, error: object | None = None) -> tuple[set[str], dict[str, object]]:
    metadata: dict[str, object] = {"parse": "unavailable"}
    if error is not None:
        metadata["error"] = str(error)
    return _base_anchors(path), metadata


def _valid_unicode(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _csv_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    rows = 0
    fields: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            if not fields or any(not field for field in fields):
                raise ValueError("CSV header contains a missing field name.")
            if len(fields) != len(set(fields)):
                raise ValueError("CSV header contains duplicate field names.")
            for row_number, row in enumerate(reader, start=1):
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"CSV row {row_number} does not match the header width.")
                rows += 1
                anchors.add(f"row:{row_number}")
                for field in fields:
                    anchors.add(f"row:{row_number}/field:{field}")
                _check_anchor_budget(anchors)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        return _unavailable(path, exc)
    return anchors, {"rows": rows, "fields": fields}


def _json_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    try:
        value = read_json(path)
        # Keep the original shallow anchors for compatibility and add escaped
        # JSON Pointer-style paths for nested evidence.
        anchors.add("json:/")
        pointers = 1
        stack: list[tuple[str, object]] = [("", value)]
        while stack:
            pointer, current = stack.pop()
            if isinstance(current, dict):
                for key, child in current.items():
                    escaped = key.replace("~", "~0").replace("/", "~1")
                    child_pointer = f"{pointer}/{escaped}"
                    anchors.add(f"json:{child_pointer}")
                    pointers += 1
                    _check_anchor_budget(anchors)
                    stack.append((child_pointer, child))
            elif isinstance(current, list):
                for index, child in enumerate(current):
                    child_pointer = f"{pointer}/{index}"
                    anchors.add(f"json:{child_pointer}")
                    pointers += 1
                    _check_anchor_budget(anchors)
                    stack.append((child_pointer, child))
        if isinstance(value, dict):
            anchors.update(f"key:{key}" for key in value)
            metadata = {"top_level": "object", "keys": sorted(value)}
        elif isinstance(value, list):
            anchors.update(f"item:{index}" for index in range(len(value)))
            metadata = {"top_level": "array", "items": len(value)}
        else:
            metadata = {"top_level": type(value).__name__}
        _check_anchor_budget(anchors)
        metadata["json_pointers"] = pointers
        return anchors, metadata
    except (OSError, UnicodeError, ValueError) as exc:
        return _unavailable(path, exc)


def _text_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    line_count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_count, _line in enumerate(handle, start=1):
                anchors.add(f"line:{line_count}")
                _check_anchor_budget(anchors)
    except (OSError, UnicodeError, ValueError) as exc:
        return _unavailable(path, exc)
    return anchors, {"lines": line_count}


def _docx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    root = _zip_xml(path, "word/document.xml")
    if root is None:
        return _unavailable(path)
    paragraphs = root.findall(".//w:p", _NS)
    tables = root.findall(".//w:tbl", _NS)
    anchors.update(f"paragraph:{index}" for index in range(1, len(paragraphs) + 1))
    try:
        _check_anchor_budget(anchors)
    except _SourceLimitError:
        return _unavailable(path, "Source contains too many indexable anchors.")
    for table_number, table in enumerate(tables, start=1):
        rows = table.findall("./w:tr", _NS)
        for row_number, row in enumerate(rows, start=1):
            cells = row.findall("./w:tc", _NS)
            for cell_number, _cell in enumerate(cells, start=1):
                anchors.add(f"table:{table_number}/row:{row_number}/cell:{cell_number}")
                try:
                    _check_anchor_budget(anchors)
                except _SourceLimitError:
                    return _unavailable(path, "Source contains too many indexable anchors.")
    return anchors, {"paragraphs": len(paragraphs), "tables": len(tables)}


def _pptx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    slide_numbers: set[int] = set()
    image_count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            members = _archive_members(archive)
            presentation_parts = {"ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"}
            if len(presentation_parts & members) == 1:
                raise ValueError("PPTX presentation metadata is incomplete.")
            if presentation_parts <= members:
                presentation = _read_xml(archive, "ppt/presentation.xml")
                targets = _relationship_targets(archive, "ppt/_rels/presentation.xml.rels")
                ordered_slides = []
                for slide_number, slide in enumerate(presentation.findall(".//p:sldIdLst/p:sldId", _NS), start=1):
                    relation_id = slide.attrib.get(f"{{{_OFFICE_REL_NS}}}id", "")
                    member = _archive_target("ppt", targets.get(relation_id, ""))
                    if member not in members:
                        raise KeyError(f"Missing slide relationship target: {relation_id}")
                    ordered_slides.append((slide_number, member))
            else:
                ordered_slides = [
                    (int(re.search(r"slide(\d+)\.xml", member).group(1)), member)
                    for member in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", member)
                ]
            for slide_number, member in ordered_slides:
                slide_numbers.add(slide_number)
                root = _read_xml(archive, member)
                text_count = len(root.findall(".//a:t", _NS))
                anchors.add(f"slide:{slide_number}")
                if text_count:
                    anchors.add(f"slide:{slide_number}/text")
                anchors.add(f"slide:{slide_number}/text-count:{text_count}")
                _check_anchor_budget(anchors)
            image_count = len([member for member in members if member.startswith("ppt/media/")])
    except _OFFICE_ERRORS:
        return _unavailable(path)
    return anchors, {"slides": sorted(slide_numbers), "images": image_count}


def _xlsx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = _archive_members(archive)
            workbook = _read_xml(archive, "xl/workbook.xml")
            rel_map = _relationship_targets(archive, "xl/_rels/workbook.xml.rels")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in members:
                shared_root = _read_xml(archive, "xl/sharedStrings.xml")
                shared_strings = [
                    "".join(node.text or "" for node in item.findall(".//s:t", _NS))
                    for item in shared_root.findall("s:si", _NS)
                ]
            sheets: list[str] = []
            cell_count = 0
            for sheet in workbook.findall(".//s:sheets/s:sheet", _NS):
                name = sheet.attrib.get("name", "Sheet")
                if not name or name in sheets:
                    raise ValueError("Workbook contains a missing or duplicate sheet name.")
                relation_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = rel_map.get(relation_id, "")
                member = _archive_target("xl", target)
                if member not in members:
                    raise KeyError(f"Missing worksheet relationship target: {relation_id}")
                sheets.append(name)
                anchors.add(f"sheet:{name}")
                sheet_root = _read_xml(archive, member)
                seen_cells: set[str] = set()
                for cell in sheet_root.findall(".//s:c", _NS):
                    ref = cell.attrib.get("r")
                    if not ref:
                        continue
                    if ref in seen_cells:
                        raise ValueError(f"Worksheet contains a duplicate cell reference: {ref}")
                    seen_cells.add(ref)
                    anchors.add(f"sheet:{name}/cell:{ref}")
                    match = _CELL_RE.match(ref)
                    if match:
                        anchors.add(f"sheet:{name}/row:{match.group(2)}")
                    cell_count += 1
                    value_node = cell.find("s:v", _NS)
                    value = value_node.text if value_node is not None else None
                    if cell.attrib.get("t") == "s" and value is not None:
                        if not value.isdigit() or int(value) >= len(shared_strings):
                            raise ValueError(f"Worksheet has an invalid shared-string index at {ref}.")
                        value = shared_strings[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(node.text or "" for node in cell.findall(".//s:t", _NS))
                    if value and _valid_unicode(value) and len(value) <= _MAX_VALUE_ANCHOR_CHARS:
                        anchors.add(f"sheet:{name}/cell:{ref}/value:{value}")
                    _check_anchor_budget(anchors)
            return anchors, {"sheets": sheets, "cells": cell_count}
    except _OFFICE_ERRORS:
        return _unavailable(path)


_SOURCE_INDEXERS = {
    ".csv": _csv_anchors,
    ".json": _json_anchors,
    ".md": _text_anchors,
    ".txt": _text_anchors,
    ".m": _text_anchors,
    ".docx": _docx_anchors,
    ".docm": _docx_anchors,
    ".pptx": _pptx_anchors,
    ".pptm": _pptx_anchors,
    ".xlsx": _xlsx_anchors,
    ".xlsm": _xlsx_anchors,
}


def _stat_signature(stat: os.stat_result) -> tuple[int, int, int, int]:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def index_file(root: Path, relative_path: str) -> SourceSnapshot | None:
    """Return one immutable snapshot, or ``None`` when the file is absent."""

    try:
        root = root.resolve()
        path = (root / relative_path).resolve()
        path.relative_to(root)
    except (OSError, ValueError):
        # Do not even hash or parse a path that escapes the selected root,
        # is invalid, or is a symlink that resolves outside it.
        return None
    if not path.is_file():
        return None
    try:
        before_hash = path.stat()
        sha256 = _sha256(path)
        after_hash = path.stat()
    except OSError:
        return None
    suffix = path.suffix.lower()
    parser = _SOURCE_INDEXERS.get(suffix)
    if suffix in _TEXT_SOURCE_SUFFIXES and after_hash.st_size > _MAX_TEXT_SOURCE_BYTES:
        anchors, metadata = _unavailable(path, "Text source exceeds the indexing byte budget.")
        kind = suffix[1:]
    elif parser is not None:
        anchors, metadata = parser(path)
        kind = suffix[1:]
    else:
        anchors = _base_anchors(path)
        metadata = {"parse": "file-only", "suffix": suffix}
        kind = suffix[1:] if suffix else "file"
    try:
        after_parse = path.stat()
        if _stat_signature(before_hash) != _stat_signature(after_hash) or _stat_signature(after_hash) != _stat_signature(after_parse):
            metadata = {**metadata, "integrity": "changed"}
        return SourceSnapshot(
            path=relative_path,
            kind=kind,
            sha256=sha256,
            size_bytes=after_parse.st_size,
            anchors=frozenset(anchors),
            metadata=metadata,
        )
    except OSError:
        return None


def index_manifest_sources(root: Path, manifest: ProjectManifest) -> tuple[SourceSnapshot, ...]:
    """Index all declared sources that exist; missing sources are validator errors."""

    snapshots: list[SourceSnapshot] = []
    for spec in manifest.sources:
        if spec.path and (snapshot := index_file(root, spec.path)) is not None:
            snapshots.append(snapshot)
    return tuple(snapshots)
