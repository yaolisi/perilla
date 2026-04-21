# Frontend API Usage Guide

## Workflow Editor APIs

Used by `EditWorkflowView` and `NodeConfigPanel`.

## Endpoints

### Get workflow

- Method: `GET`
- Path: `/api/v1/workflows/{workflow_id}`
- Client: `getWorkflow(workflowId)`

### Get workflow version

- Method: `GET`
- Path: `/api/v1/workflows/{workflow_id}/versions/{version_id}`
- Client: `getWorkflowVersion(workflowId, versionId)`

### Update workflow metadata

- Method: `PATCH`
- Path: `/api/v1/workflows/{workflow_id}`
- Client: `updateWorkflow(workflowId, payload)`

### Create workflow version

- Method: `POST`
- Path: `/api/v1/workflows/{workflow_id}/versions`
- Client: `createWorkflowVersion(workflowId, payload)`

### List models

- Method: `GET`
- Path: `/api/v1/models`
- Client: `listModels()`
- UI usage: node config panel LLM model selector

### List agents

- Method: `GET`
- Path: `/api/v1/agents`
- Client: `listAgents()`
- UI usage: node config panel Agent selector

### List tools

- Method: `GET`
- Path: `/api/v1/tools`
- Client: `listTools()`
- UI usage: node config panel Tool selector

## API Error Handling

- non-2xx responses throw error in `apiFetch` wrappers
- workflow editor keeps current draft state and surfaces validation or save failure
- preflight checks run before save/run to reduce invalid executions
