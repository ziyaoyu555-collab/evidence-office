"""Deterministic, dependency-free source indexing for common Office inputs."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree

from .model import ProjectManifest, SourceSnapshot


_CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_xml(path: Path, member: str) -> ElementTree.Element | None:
    try:
        with zipfile.ZipFile(path) as archive:
            return ElementTree.fromstring(archive.read(member))
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return None


def _base_anchors(path: Path) -> set[str]:
    return {"file", f"file:{path.name}"}


def _csv_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    rows = 0
    fields: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = [field for field in (reader.fieldnames or []) if field]
            for row_number, _row in enumerate(reader, start=1):
                rows += 1
                anchors.add(f"row:{row_number}")
                for field in fields:
                    anchors.add(f"row:{row_number}/field:{field}")
    except (OSError, UnicodeError, csv.Error) as exc:
        return anchors, {"parse": "unavailable", "error": str(exc)}
    return anchors, {"rows": rows, "fields": fields}


def _json_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return anchors, {"parse": "unavailable", "error": str(exc)}
    if isinstance(value, dict):
        anchors.update(f"key:{key}" for key in value)
        metadata = {"top_level": "object", "keys": sorted(value)}
    elif isinstance(value, list):
        anchors.update(f"item:{index}" for index in range(len(value)))
        metadata = {"top_level": "array", "items": len(value)}
    else:
        metadata = {"top_level": type(value).__name__}
    return anchors, metadata


def _text_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            line_count = sum(1 for _ in handle)
    except (OSError, UnicodeError) as exc:
        return anchors, {"parse": "unavailable", "error": str(exc)}
    anchors.update(f"line:{number}" for number in range(1, line_count + 1))
    return anchors, {"lines": line_count}


def _docx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    root = _zip_xml(path, "word/document.xml")
    if root is None:
        return anchors, {"parse": "unavailable"}
    paragraphs = root.findall(".//w:p", _NS)
    tables = root.findall(".//w:tbl", _NS)
    anchors.update(f"paragraph:{index}" for index in range(1, len(paragraphs) + 1))
    for table_number, table in enumerate(tables, start=1):
        rows = table.findall("./w:tr", _NS)
        for row_number, row in enumerate(rows, start=1):
            cells = row.findall("./w:tc", _NS)
            for cell_number, _cell in enumerate(cells, start=1):
                anchors.add(f"table:{table_number}/row:{row_number}/cell:{cell_number}")
    return anchors, {"paragraphs": len(paragraphs), "tables": len(tables)}


def _pptx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    slide_numbers: set[int] = set()
    image_count = 0
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.namelist()
            slide_members = [member for member in members if re.fullmatch(r"ppt/slides/slide\d+\.xml", member)]
            for member in slide_members:
                slide_number = int(re.search(r"slide(\d+)\.xml", member).group(1))
                slide_numbers.add(slide_number)
                root = ElementTree.fromstring(archive.read(member))
                text_count = len(root.findall(".//a:t", _NS))
                anchors.add(f"slide:{slide_number}")
                anchors.add(f"slide:{slide_number}/text")
                anchors.add(f"slide:{slide_number}/text-count:{text_count}")
            image_count = len([member for member in members if member.startswith("ppt/media/")])
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return anchors, {"parse": "unavailable"}
    return anchors, {"slides": sorted(slide_numbers), "images": image_count}


def _xlsx_anchors(path: Path) -> tuple[set[str], dict[str, object]]:
    anchors = _base_anchors(path)
    try:
        with zipfile.ZipFile(path) as archive:
            workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
            rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relationship_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
            rel_map = {
                relation.attrib.get("Id", ""): relation.attrib.get("Target", "")
                for relation in rels.findall(f"{{{relationship_ns}}}Relationship")
            }
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in archive.namelist():
                shared_root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(node.text or "" for node in item.findall(".//s:t", _NS))
                    for item in shared_root.findall("s:si", _NS)
                ]
            sheets: list[str] = []
            cell_count = 0
            for sheet in workbook.findall(".//s:sheets/s:sheet", _NS):
                name = sheet.attrib.get("name", "Sheet")
                relation_id = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id", "")
                target = rel_map.get(relation_id, "")
                member = target.lstrip("/")
                if not member.startswith("xl/"):
                    member = f"xl/{member}"
                sheets.append(name)
                anchors.add(f"sheet:{name}")
                if member not in archive.namelist():
                    continue
                sheet_root = ElementTree.fromstring(archive.read(member))
                for cell in sheet_root.findall(".//s:c", _NS):
                    ref = cell.attrib.get("r")
                    if not ref:
                        continue
                    anchors.add(f"sheet:{name}/cell:{ref}")
                    match = _CELL_RE.match(ref)
                    if match:
                        anchors.add(f"sheet:{name}/row:{match.group(2)}")
                    cell_count += 1
                    if cell.attrib.get("t") == "s":
                        value = cell.find("s:v", _NS)
                        if value is not None and value.text and value.text.isdigit():
                            index = int(value.text)
                            if index < len(shared_strings):
                                anchors.add(f"sheet:{name}/cell:{ref}/value:{shared_strings[index]}")
            return anchors, {"sheets": sheets, "cells": cell_count}
    except (KeyError, ElementTree.ParseError, zipfile.BadZipFile):
        return anchors, {"parse": "unavailable"}


def index_file(root: Path, relative_path: str) -> SourceSnapshot | None:
    """Return one immutable snapshot, or ``None`` when the file is absent."""

    path = (root / relative_path).resolve()
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix == ".csv":
        anchors, metadata = _csv_anchors(path)
        kind = "csv"
    elif suffix == ".json":
        anchors, metadata = _json_anchors(path)
        kind = "json"
    elif suffix in {".md", ".txt", ".m"}:
        anchors, metadata = _text_anchors(path)
        kind = suffix[1:]
    elif suffix == ".docx":
        anchors, metadata = _docx_anchors(path)
        kind = "docx"
    elif suffix == ".pptx":
        anchors, metadata = _pptx_anchors(path)
        kind = "pptx"
    elif suffix == ".xlsx":
        anchors, metadata = _xlsx_anchors(path)
        kind = "xlsx"
    else:
        anchors = _base_anchors(path)
        metadata = {"parse": "file-only", "suffix": suffix}
        kind = suffix[1:] if suffix else "file"
    return SourceSnapshot(
        path=relative_path,
        kind=kind,
        sha256=_sha256(path),
        size_bytes=path.stat().st_size,
        anchors=frozenset(anchors),
        metadata=metadata,
    )


def index_manifest_sources(root: Path, manifest: ProjectManifest) -> tuple[SourceSnapshot, ...]:
    """Index all declared sources that exist; missing sources are validator errors."""

    snapshots: list[SourceSnapshot] = []
    for spec in manifest.sources:
        if spec.path and (snapshot := index_file(root, spec.path)) is not None:
            snapshots.append(snapshot)
    return tuple(snapshots)
