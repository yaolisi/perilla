# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- frontend unit test setup with Vitest + Vue Test Utils
- component test coverage for workflow node config searchable selectors
- Cypress e2e setup and workflow editor smoke flow
- frontend docs:
  - component documentation (`docs/frontend/COMPONENTS.md`)
  - API usage documentation (`docs/frontend/API.md`)
  - developer usage guide (`docs/frontend/USAGE.md`)
- split Vite configs:
  - `frontend/vite.config.dev.ts`
  - `frontend/vite.config.prod.ts`
  - shared config in `frontend/vite.config.shared.ts`

### Changed

- improved workflow editor UX:
  - searchable model/agent/tool selectors
  - grid snapping and drag-end alignment on workflow canvas
  - clearer action copy in top toolbar
  - accessibility semantics in editor side panels and config sections
- updated frontend npm scripts for dev/build/test workflows
- updated `frontend/README.md` with project-specific guidance

### Fixed

- workflow repository UTC handling migrated to timezone-aware timestamp logic
