# Frontend Components Guide

## Scope

This document focuses on high-impact UI components introduced in the workflow editor UX upgrade.

## Core Components

### `WorkflowCanvas`

- Location: `frontend/src/components/workflow/editor/WorkflowCanvas.vue`
- Responsibility:
  - render graph canvas via Vue Flow
  - handle node/edge updates
  - keep selection state in sync with parent editor
  - apply drag-end grid snapping (`16x16`) for better alignment
- Key events:
  - `update:nodes`
  - `update:edges`
  - `select-node`
  - `select-node-by-id`
  - `select-edge`

### `NodeConfigPanel`

- Location: `frontend/src/components/workflow/editor/NodeConfigPanel.vue`
- Responsibility:
  - display/edit node-specific runtime config
  - provide model/agent/tool selectors
  - validate key node configs before save
  - support searchable selectors for large datasets
- Search fields:
  - model search: filter by display name, model ID, backend
  - agent search: filter by agent name and agent ID
  - tool search: filter by display name and tool name

### `EditWorkflowView`

- Location: `frontend/src/components/workflow/EditWorkflowView.vue`
- Responsibility:
  - orchestrate workflow editing screen
  - manage undo/redo history
  - run preflight checks
  - save and run workflows
  - host left node library and right config panel with accessibility labels

## Accessibility Notes

- side panels use explicit region labels:
  - `aria-label="节点库面板"`
  - `aria-label="节点配置面板"`
- config section titles use text semantics where no explicit form control binding exists.
