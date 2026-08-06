"""Machine-checked architecture contracts for the web UI phase."""

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts/web"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_api_inventory_has_unique_classified_operations_and_safe_confirmations() -> None:
    contract = _load("api-routes-v1.json")
    allowed_classes = set(contract["operation_classes"])
    routes = contract["routes"]
    identities = [(route["method"], route["path"]) for route in routes]

    assert contract["base_path"] == "/api/v1"
    assert len(identities) == len(set(identities))
    assert all(route["class"] in allowed_classes for route in routes)
    assert all(
        route["confirmation"] != "none"
        for route in routes
        if route["class"] in {"local_mutation", "expensive_run", "forbidden"}
    )
    assert all(
        route["class"] == "forbidden" for route in routes if route["path"].startswith("/github/")
    )
    assert not any(
        route["class"] == "forbidden" and route["confirmation"] != "unavailable" for route in routes
    )


def test_resource_contracts_exclude_secrets_and_raw_observation_payloads() -> None:
    contract = _load("resources-v1.json")
    forbidden = set(contract["forbidden_fields"])
    fields = {
        field for resource_fields in contract["resources"].values() for field in resource_fields
    }

    assert forbidden.isdisjoint(fields)
    assert "merge_is_heuristic" in contract["resources"]["opportunity_summary"]
    assert "explanation" in contract["resources"]["opportunity_detail"]
    assert "source" in contract["resources"]["config_revision"]


def test_design_tokens_define_two_accessible_themes_and_responsive_layouts() -> None:
    contract = _load("design-tokens-v1.json")
    breakpoints = contract["breakpoints"]
    themes = contract["themes"]
    required_colors = {
        "canvas",
        "surface",
        "raised",
        "border",
        "text",
        "muted",
        "accent",
        "positive",
        "warning",
        "danger",
    }

    assert 0 < breakpoints["compact"] < breakpoints["tablet"] < breakpoints["desktop"]
    assert set(themes) == {"dark", "light"}
    assert all(set(theme) == required_colors for theme in themes.values())
    assert contract["focus"]["width"] >= 2
    assert contract["motion"]["reduced_motion"] is True


def test_architecture_documents_every_primary_route_and_keyboard_contract() -> None:
    architecture = (ROOT / "docs/web/ARCHITECTURE.md").read_text(encoding="utf-8")
    wireframes = (ROOT / "docs/web/WIREFRAMES.md").read_text(encoding="utf-8")

    for route in (
        "Home",
        "Assistant",
        "Opportunities",
        "Repositories",
        "Preferences",
        "Runs",
        "Settings",
    ):
        assert route in architecture
        assert f"## {route}" in wireframes
    for key in ("Tab", "Cmd/Ctrl+K", "Escape"):
        assert key in architecture
    assert "untrusted" in architecture.casefold()
    assert "GitHub mutations are unavailable" in architecture
