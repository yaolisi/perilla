from __future__ import annotations

from fastapi.testclient import TestClient

from api import events as events_api

from tests.helpers import build_minimal_router_test_client


def _build_client() -> TestClient:
    return build_minimal_router_test_client(events_api)


def test_openapi_events_named_schemas() -> None:
    client = _build_client()
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    lst = paths["/api/events/instance/{instance_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert lst == "#/components/schemas/EventListResponse"
    assert schemas["EventListResponse"]["properties"]["events"]["items"]["$ref"] == "#/components/schemas/EventResponse"
    assert schemas["EventResponse"]["properties"]["payload"]["$ref"] == "#/components/schemas/EventPayload"

    ag = paths["/api/events/agent-session/{session_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert ag == "#/components/schemas/AgentSessionEventsResponse"
    inst = schemas["AgentSessionEventsResponse"]["properties"]["instances"]
    assert inst["$ref"] == "#/components/schemas/AgentSessionInstancesMap"
    assert (
        schemas["AgentSessionInstancesMap"]["additionalProperties"]["items"]["$ref"]
        == "#/components/schemas/EventResponse"
    )

    br = paths["/api/events/instance/{instance_id}/event-types"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert br == "#/components/schemas/EventTypeBreakdownResponse"
    assert (
        schemas["EventTypeBreakdownResponse"]["properties"]["breakdown"]["$ref"]
        == "#/components/schemas/EventTypeBreakdownCounts"
    )

    rp = paths["/api/events/instance/{instance_id}/replay"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert rp == "#/components/schemas/RebuiltStateResponse"
    rs = schemas["RebuiltStateResponse"]
    assert rs["properties"]["nodes"]["$ref"] == "#/components/schemas/ReplayGraphNodesMap"
    assert (
        schemas["ReplayGraphNodesMap"]["additionalProperties"]["$ref"]
        == "#/components/schemas/GraphNodeStateSnapshot"
    )
    assert rs["properties"]["context"]["$ref"] == "#/components/schemas/ReplayContextSnapshot"

    vl = paths["/api/events/instance/{instance_id}/validate"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert vl == "#/components/schemas/ValidationResponse"

    mt = paths["/api/events/instance/{instance_id}/metrics"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
        "$ref"
    ]
    assert mt == "#/components/schemas/MetricsResponse"
    assert schemas["MetricsResponse"]["properties"]["details"]["$ref"] == "#/components/schemas/MetricsDetailsSnapshot"
