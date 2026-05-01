from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import backup as backup_api
from api import model_backups as model_backups_api
from api.errors import register_error_handlers
from core.security.deps import require_authenticated_platform_admin


def _client_with(*routers) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    for r in routers:
        app.include_router(r)
    app.dependency_overrides[require_authenticated_platform_admin] = lambda: None
    return TestClient(app)


def test_openapi_database_backup_named_schemas() -> None:
    client = _client_with(backup_api.router)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    st = paths["/api/backup/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert st == "#/components/schemas/DatabaseStatusResponse"

    cg = paths["/api/backup/config"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cg == "#/components/schemas/BackupConfigReadResponse"

    cp = paths["/api/backup/config"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cp == "#/components/schemas/BackupConfigUpdateResponse"

    cr = paths["/api/backup/create"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert cr == "#/components/schemas/BackupCreateResponse"

    rs = paths["/api/backup/restore/{backup_id}"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert rs == "#/components/schemas/BackupRestoreResponse"

    hist = paths["/api/backup/history"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert hist.get("items", {}).get("$ref") == "#/components/schemas/BackupHistoryEntry"

    de = paths["/api/backup/{backup_id}"]["delete"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert de == "#/components/schemas/BackupDeleteResponse"

    br = paths["/api/backup/browse-directory"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert br == "#/components/schemas/BackupBrowseDirectoryResponse"

    assert schemas["BackupCreateResponse"]["properties"]["success"]["const"] is True


def test_openapi_model_json_backup_named_schemas() -> None:
    client = _client_with(model_backups_api.router)
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths") or {}
    schemas = spec.get("components", {}).get("schemas") or {}

    assert (
        paths["/api/model-backups/status"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupStatusResponse"
    )

    assert (
        paths["/api/model-backups/create"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupCreateOkResponse"
    )

    assert (
        paths["/api/model-backups/create-all"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupCreateAllResponse"
    )

    lst = paths["/api/model-backups"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert lst.get("items", {}).get("$ref") == "#/components/schemas/ModelJsonBackupListItem"

    assert (
        paths["/api/model-backups/delete"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupDeleteOkResponse"
    )

    assert (
        paths["/api/model-backups/restore"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupRestoreOkResponse"
    )

    assert (
        paths["/api/model-backups/restore-batch"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonBackupRestoreBatchResponse"
    )

    assert (
        paths["/api/model-backups/retention-dry-run"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonRetentionDryRunResponse"
    )

    assert (
        paths["/api/model-backups/cleanup"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ModelJsonCleanupResponse"
    )

    assert (
        paths["/api/model-backups/daily-manifests/{date_yyyymmdd}"]["get"]["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        == "#/components/schemas/ModelJsonDailyManifestResponse"
    )

    cac = schemas["ModelJsonBackupCreateAllResponse"]
    assert cac["properties"]["created"]["items"]["$ref"] == "#/components/schemas/ModelJsonBackupOpCreatedRow"
    assert cac["properties"]["failed"]["items"]["$ref"] == "#/components/schemas/ModelJsonBackupOpFailedRow"

    rb = schemas["ModelJsonBackupRestoreBatchResponse"]
    assert rb["properties"]["restored"]["items"]["$ref"] == "#/components/schemas/ModelJsonBackupRestoreRestoredRow"
    assert rb["properties"]["failed"]["items"]["$ref"] == "#/components/schemas/ModelJsonBackupOpFailedRow"

    rd = schemas["ModelJsonRetentionDryRunResponse"]
    assert rd["properties"]["to_delete"]["items"]["$ref"] == "#/components/schemas/ModelJsonRetentionDeleteCandidate"

    dm = schemas["ModelJsonDailyManifestResponse"]
    assert dm["properties"]["backups"]["items"]["$ref"] == "#/components/schemas/ModelJsonBackupOpCreatedRow"

    err_prop = schemas["ModelJsonCleanupResponse"]["properties"]["errors"]
    err_item_refs = [
        opt.get("items", {}).get("$ref")
        for opt in (err_prop.get("anyOf") or [])
        if isinstance(opt, dict) and opt.get("type") == "array"
    ]
    assert "#/components/schemas/ModelJsonCleanupErrorRow" in err_item_refs
