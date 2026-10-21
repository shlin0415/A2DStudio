# A2D Project Package v2 Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace A2D's envelope-based ZIP v1 with a strict, portable ZIP v2 containing explicitly referenced project media and no machine-local identities or configuration.

**Architecture:** Define a portable project schema separate from `ExportEnvelope`. Export resolves only known local A2D media routes and the configured reference WAV for each used speaker, then writes deduplicated assets under `assets/`. Import streams ZIP entries through fflate's `Unzip` API, enforces path, count and byte limits while data arrives, validates a complete v2 project before touching stores, then creates runtime Blob URLs and local numeric role IDs from portable role keys.

**Tech Stack:** Vue 3, TypeScript, Pinia, Vitest, `fflate` 0.8.3; FastAPI, `FileResponse`, pytest.

## Implementation status (2026-10-22)

- ZIP v2 export/import is implemented. Export serializes an allowlisted manifest and packages each referenced media kind under `assets/`; import rejects v1, unsafe paths, undeclared resources, size violations, unsupported ZIP metadata, and CRC mismatches before updating stores.
- Runtime roles are rebuilt from `script_role_key`; avatar images use packaged Blob URLs. The backend reference WAV route serves only configured audio within each role's asset root and does not return local paths.
- Verification: frontend `pnpm test` passes 140 tests across 17 files; `pnpm build-only` succeeds; `tests/test_a2d_project_assets.py` passes 4 tests with `--noconftest`. `pnpm type-check` still reports six errors in untouched LingChat UI/audio files.
- Process note: the Task 4 import contract tests were added after the first implementation pass rather than run as a red test before coding; they now cover round-trip restore, v1 rejection, unsafe and duplicate paths, CRC, limits, rollback, and avatar URLs.
- The worktree also contains pre-existing edits to the main development roadmap and game-data YAML line endings; they were not included in the implementation commit.

---

## File map

- `frontend_vue/src/composables/a2d-project-format.ts` — v2 manifest types, portable field mapping, path/media/manifest validation, package limits.
- `frontend_vue/src/composables/useA2DProject.ts` — asset collection, ZIP v2 export, streamed bounded import, `importSession` integration.
- `frontend_vue/src/composables/a2d-project-runtime-assets.ts` — reactive runtime avatar mapping keyed by stable speaker key and URL lifecycle for the active imported package.
- `frontend_vue/src/stores/modules/game/state.ts` — optional runtime `scriptRoleKey` field; never serialized as a numeric role ID.
- `frontend_vue/src/composables/useA2DWebSocket.ts` — retain the existing stable `script_role_key` from `a2d.characters` in runtime GameRole objects.
- `frontend_vue/src/composables/useA2DReplay.ts` — resolve replay roles by stable `scriptRoleKey` before display-name fallback.
- `frontend_vue/src/components/game/standard/GameRoleAvatar.vue` — render packaged avatar Blob URLs for imported project roles.
- `frontend_vue/src/composables/__tests__/useA2DProject.test.ts` — export/import, schema, asset closure, v1 rejection, size and path, CRC and size-boundary tests.
- `ling_chat/core/a2d_project_assets.py` — pure configured-reference path resolver with directory containment checks; no service manager or `.env` import.
- `ling_chat/api/a2d_project_assets.py` — thin read-only route for the configured GSV reference WAV of an active A2D speaker; return bytes without exposing server paths.
- `ling_chat/api/routes_manager.py` — register the reference-audio route.
- `tests/test_a2d_project_assets.py` — path-containment and environment-override tests for the pure resolver.

## Task 1: Define the portable schema and prove runtime IDs are absent

**Files:**
- Create: `frontend_vue/src/composables/a2d-project-format.ts`
- Modify: `frontend_vue/src/composables/__tests__/useA2DProject.test.ts`

- [x] **Step 1: Write a failing v2 schema test**

Create a minimal v2 manifest fixture with `format`, `schema_version`, `title`, `exported_at`, `roles`, `script`, and `resources`. Assert that a valid role key and relative resource reference pass, while an unknown schema version and a `..` resource path fail with a field-specific error.

- [x] **Step 2: Run the focused test and confirm the missing v2 validator failure**

Run from `frontend_vue/`: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts -t "v2 schema"`.

Expected: FAIL because the v2 validator is not implemented.

- [x] **Step 3: Implement the minimal portable types and validator**

Define project roles by `script_role_key`; define project lines with speaker keys and an optional `character_role_key`; define resources as `{ path, kind, media_type, byte_length }`. Only allow project line fields, overlay presentation fields, the GSV parameter keys `speed_factor`, `top_k`, `top_p`, and `temperature`, and visual role fields needed to render. Reject unknown top-level schema versions and resource references outside their matching `assets/` category.

- [x] **Step 4: Run the focused schema test**

Run: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts -t "v2 schema"`.

Expected: PASS; no production exporter changes in this task.

- [x] **Step 5: Commit the schema boundary**

```powershell
git add frontend_vue/src/composables/a2d-project-format.ts frontend_vue/src/composables/__tests__/useA2DProject.test.ts
git commit -m "feat: define portable A2D project v2 schema"
```

## Task 2: Resolve configured GSV reference WAVs without exposing paths

**Files:**
- Create: `ling_chat/core/a2d_project_assets.py`
- Create: `ling_chat/api/a2d_project_assets.py`
- Modify: `ling_chat/api/routes_manager.py`
- Create: `tests/test_a2d_project_assets.py`

- [x] **Step 1: Write failing resolver tests**

Import `resolve_reference_audio_path` from `ling_chat.core.a2d_project_assets` and test `(reference_path, character_root, has_environment_override)` with these cases: a WAV below the configured character root succeeds; a path outside the root fails; a missing file fails; and an environment-provided GSV reference fails without including its value in the error.

- [x] **Step 2: Run the backend test and confirm the resolver is missing**

Run from the repository root: `uv run pytest tests/test_a2d_project_assets.py -q`.

Expected: FAIL because the resolver does not exist.

- [x] **Step 3: Implement the pure containment resolver and read-only route**

The pure resolver lives in `ling_chat/core/a2d_project_assets.py` and imports only the standard library. The route accepts one speaker key, looks it up only in `service_manager.ai_service.a2d_session.characters`, reads the active GSV adapter's `ref_audio_path`, and passes it to the resolver with that speaker's configured `VoiceMaker.character_path`. If `GPT_SOVITS_REF_AUDIO` is non-empty, reject the export without logging or returning the value. Return a WAV `FileResponse`; never accept a filesystem path from the request and never return a path in JSON.

- [x] **Step 4: Run the backend resolver tests**

Run: `uv run pytest tests/test_a2d_project_assets.py -q`.

Expected: all resolver tests pass without starting GSV or reading `.env` content.

- [x] **Step 5: Commit the backend reference boundary**

```powershell
git add ling_chat/core/a2d_project_assets.py ling_chat/api/a2d_project_assets.py ling_chat/api/routes_manager.py tests/test_a2d_project_assets.py
git commit -m "feat: expose configured A2D reference audio safely"
```

## Task 3: Export a clean v2 project and all explicit media references

**Files:**
- Modify: `frontend_vue/src/composables/useA2DProject.ts`
- Modify: `frontend_vue/src/stores/modules/game/state.ts`
- Modify: `frontend_vue/src/composables/useA2DWebSocket.ts`
- Modify: `frontend_vue/src/composables/__tests__/useA2DProject.test.ts`

- [x] **Step 1: Write failing export contract tests**

Cover a project with two `script_role_key` roles, one line WAV, stage and line backgrounds, one image overlay, BGM, a reference WAV, and one used avatar emotion per speaker. Assert each unique source is fetched once; archive paths are relative; the manifest has `schema_version: 2`; no `gameRoles`, `roleId`, `character_folder`, absolute path, endpoint, or arbitrary `gsv_params` key appears; and a missing non-empty reference makes export fail with its field location.

- [x] **Step 2: Run the export contract tests and confirm the current v1 output violates them**

Run: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts -t "export contract"`.

Expected: FAIL because the current ZIP writes `version: 1` and serializes the complete envelope.

- [x] **Step 3: Carry the stable speaker key in runtime GameRole data**

Add optional `scriptRoleKey?: string` to `GameRole`; set it from each `a2d.characters` payload's existing `script_role_key`. Keep `roleId` as runtime-only state.

- [x] **Step 4: Implement whitelisted source resolution and portable serialization**

Resolve background files only through `/api/v1/chat/script/background_file/` or `/api/v1/chat/background/background_file/`; image overlays through `/api/v1/chat/script/pic_file/`; BGM through `/api/v1/chat/script/music_file/` or `/api/v1/chat/back-music/music_file/`; role avatars through `/api/v1/chat/character/get_avatar/`; WAV references through the new A2D route. Only accept same-origin known A2D routes, local `/audio/` or `/api/a2d/save/audio/` WAVs, and in-memory `blob:`/`data:` audio URLs. Reject file paths, UNC paths, external origins, unknown route shapes, missing files, and unsupported media.

Serialize an allowlist-only project manifest keyed by `script_role_key`. Map local `character_id` references to role keys and omit `roleId`, `character_folder`, service endpoints, configuration, and environment values. Deduplicate byte-identical source URLs by kind and URL. Use `assets/audio/`, `assets/backgrounds/`, `assets/images/`, `assets/music/`, `assets/references/`, and `assets/avatars/`.

- [x] **Step 5: Run focused export tests**

Run: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts -t "export contract"`.

Expected: all v2 export assertions pass and old v1 assertions have been replaced.

- [x] **Step 6: Commit export behavior**

```powershell
git add frontend_vue/src/composables/useA2DProject.ts frontend_vue/src/stores/modules/game/state.ts frontend_vue/src/composables/useA2DWebSocket.ts frontend_vue/src/composables/__tests__/useA2DProject.test.ts
git commit -m "feat: export referenced A2D project assets"
```

## Task 4: Stream, bound, validate, and restore v2 project imports

**Files:**
- Modify: `frontend_vue/src/composables/useA2DProject.ts`
- Create: `frontend_vue/src/composables/a2d-project-runtime-assets.ts`
- Modify: `frontend_vue/src/composables/useA2DReplay.ts`
- Modify: `frontend_vue/src/components/game/standard/GameRoleAvatar.vue`
- Modify: `frontend_vue/src/composables/__tests__/useA2DProject.test.ts`
- Modify: `frontend_vue/src/components/game/standard/__tests__/GameRoleAvatar.test.ts`

- [x] **Step 1: Write failing import tests**

Cover successful restoration of three lines and all bundled media as Blob URLs; strict rejection of v1/unknown format; path traversal, absolute/UNC/URL references, undeclared resources, duplicate normalized ZIP entries, corrupt input, more than 1,024 entries, a 128 MiB entry, over 512 MiB expanded total, over 512 MiB archive, a corrupted CRC, and a `project.json` above 10 MiB. Exercise the shared byte-accounting helper at exact and over-limit numeric boundaries instead of allocating a 512 MiB test archive. Assert any failed import leaves stores unchanged and revokes all Blob URLs created during that import.

- [x] **Step 2: Run import tests and confirm v1/full-buffer importer failures**

Run: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts -t "import contract"`.

Expected: FAIL because the current importer accepts v1 and calls full-buffer `unzip` without limits.

- [x] **Step 3: Implement streaming ZIP validation**

Read and validate the bounded ZIP central directory first (entry count and normalized names, CRC32, compressed/uncompressed sizes, and local-header offsets), then use `File.stream().getReader()` and fflate `Unzip` with registered `UnzipInflate`. The installed fflate streaming API does not verify CRC itself, so compute CRC32 over emitted bytes and compare it with the central-directory record. Count compressed archive bytes, entry count, actual emitted bytes per entry and across the archive while chunks arrive. Test the byte-accounting helper with numeric boundaries rather than allocating a 512 MiB fixture. Normalize and validate each path before accepting it; reject duplicate names, unsupported compression, undeclared resources and limit violations before `importSession`. Collect chunks only after per-entry bounds pass; revoke pending object URLs on any failure.

- [x] **Step 4: Restore a validated project into runtime state**

Create Blob URLs for the validated media, rewrite only the in-memory `ScriptLine`/overlay paths, and construct local numeric `GameRole` objects from project speaker keys with no machine role folder. Put project roles on a collision-free negative runtime ID range. Register avatar URLs in a Vue-reactive map by speaker key and normalized emotion; update `GameRoleAvatar` to use that map for project roles. Use the same role-key lookup in replay before its display-name fallback. Call `importSession` only after the entire ZIP and manifest are valid; on failure leave the current store and active project URLs unchanged. Reject v1 ZIPs explicitly.

- [x] **Step 5: Run focused import and avatar rendering tests**

Run: `pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts src/components/game/standard/__tests__/GameRoleAvatar.test.ts`.

Expected: all project import and avatar tests pass; stage images, backgrounds, BGM and line audio use the imported Blob URLs.

- [x] **Step 6: Commit v2 import behavior**

```powershell
git add frontend_vue/src/composables/useA2DProject.ts frontend_vue/src/composables/a2d-project-runtime-assets.ts frontend_vue/src/composables/useA2DReplay.ts frontend_vue/src/components/game/standard/GameRoleAvatar.vue frontend_vue/src/composables/__tests__/useA2DProject.test.ts frontend_vue/src/components/game/standard/__tests__/GameRoleAvatar.test.ts
git commit -m "feat: safely import A2D project v2 archives"
```

## Task 5: Verify complete frontend contract and preserve existing work

**Files:**
- No additional files; inspect only the files changed in Tasks 1–4.

- [x] **Step 1: Run all frontend unit tests**

Run from `frontend_vue/`: `pnpm test`.

Expected: all tests pass. If a failure is outside the changed files, record the exact test and existing baseline evidence; do not edit unrelated LingChat files.

- [x] **Step 2: Run the frontend production build**

Run from `frontend_vue/`: `pnpm build-only`.

Expected: Vite production build succeeds. `pnpm type-check` is not the acceptance gate because this checkout has six previously recorded errors in untouched LingChat files; still run it and confirm the error set did not increase.

- [x] **Step 3: Review and commit only the A2D v2 implementation**

Run `git diff --check`, inspect `git diff --stat`, `git diff --name-only`, and `git status --short`. Stage only the implementation files named above; leave `docs/develop/a2d-studio-development-plan.md` and all pre-existing `ling_chat/static/game_data/` line-ending changes unstaged. Commit the verified implementation with `feat: implement A2D project ZIP v2`.

- [x] **Step 4: Record the shortest verification path**

Use these commands for a reviewer rerun:

```powershell
Set-Location frontend_vue
pnpm exec vitest run src/composables/__tests__/useA2DProject.test.ts src/components/game/standard/__tests__/GameRoleAvatar.test.ts
pnpm build-only
```

For the backend resolver boundary, run from repository root: `uv run pytest tests/test_a2d_project_assets.py -q`.
