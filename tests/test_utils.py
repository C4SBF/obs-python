from __future__ import annotations

import json

import yaml

from obs.utils import dump_json, dump_yaml, to_json, to_yaml
from tests.factories import make_discovery_device, make_discovery_point


def test_to_json_serializes_dataclass_payload() -> None:
    # given
    device = make_discovery_device(points=[make_discovery_point()])

    # when
    payload = to_json(device)
    parsed = json.loads(payload)

    # then
    assert parsed["uid"] == device.uid
    assert parsed["points"][0]["uid"] == device.points[0].uid


def test_to_yaml_serializes_dataclass_payload() -> None:
    # given
    device = make_discovery_device(points=[make_discovery_point()])

    # when
    payload = to_yaml(device)
    parsed = yaml.safe_load(payload)

    # then
    assert parsed["uid"] == device.uid
    assert parsed["points"][0]["uid"] == device.points[0].uid


def test_dump_json_writes_file(tmp_path) -> None:
    # given
    out = tmp_path / "result.json"
    device = make_discovery_device(points=[make_discovery_point()])

    # when
    dump_json(device, out)
    parsed = json.loads(out.read_text(encoding="utf-8"))

    # then
    assert parsed["uid"] == device.uid


def test_dump_yaml_writes_file(tmp_path) -> None:
    # given
    out = tmp_path / "result.yaml"
    device = make_discovery_device(points=[make_discovery_point()])

    # when
    dump_yaml(device, out)
    parsed = yaml.safe_load(out.read_text(encoding="utf-8"))

    # then
    assert parsed["uid"] == device.uid
