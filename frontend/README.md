# Frontend Development Guide

## Commands

- `npm run dev`: start development server (`vite.config.dev.ts`)
- `npm run build`: production build (`vite.config.prod.ts`)
- `npm run preview`: preview production build
- `npm run test:unit`: run Vitest unit tests
- `npm run test:unit:watch`: run Vitest in watch mode
- `npm run test:e2e`: run Cypress e2e tests
- `npm run test:e2e:open`: open Cypress interactive runner

## Tenant header（与网关对齐）

控制台将当前租户写入 **`localStorage`**（键名见 `frontend/src/services/api.ts` 中 `STORAGE_TENANT_ID_KEY`），并在请求中附带 **`X-Tenant-Id`**（与后端 `TENANT_HEADER_NAME` 默认一致）。启用租户强制时，聊天、会话、知识库、记忆、工作流等路径必须与所选租户一致；排查 400/403/404 时优先核对租户与 API Key–租户绑定。详见仓库根目录 **`tutorials/tutorial.md`**。

## Documentation

- [Component docs](../docs/frontend/COMPONENTS.md)
- [Frontend API docs](../docs/frontend/API.md)
- [Developer usage guide](../docs/frontend/USAGE.md)
