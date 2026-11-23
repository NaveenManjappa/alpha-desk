# ADR 015: Angular for the web UI, starting at the end of Phase 1

Status: Accepted · 16 Nov 2026 · third slice added 23 Nov 2026 (Phase 1, Slice 16)

## Context

The architecture planned one plain HTML page, built in Phase 3. Until then the app could only be tested with a script or `curl`. That makes it slow to test by hand and hard to show to someone.

The UI will also grow: a brief view in Phase 3, a memory panel in Phase 4, approvals and a portfolio in Phase 5, sign-in in Phase 7. One HTML file with plain JavaScript gets harder to change with each of those.

The owner has long Angular experience, so an Angular app is quick to build and adds no learning cost.

## Options considered

| Option | For | Against |
|---|---|---|
| One plain HTML page, in Phase 3 | No build step. Nothing new to run. | No UI until Phase 3. Becomes hard to maintain as screens are added. |
| A Python UI library (Streamlit, Chainlit) | Very quick to start. Stays in Python. | Hides the API. Weak fit for an approvals inbox and a portfolio view. Not how a product frontend is built. |
| React | Large ecosystem. | No existing experience. Time spent learning it is time away from the agent work. |
| Angular | Existing expertise. Typed, structured, scales to several screens. | A Node toolchain and a build step beside Python. |

## Decision

Build the web UI in Angular, in a `web/` folder. The first version is built in Slices 14 and 15 of Phase 1. Slice 16 adds a list of earlier conversations.

- **Local development:** the Angular dev server, with a proxy to the API. No CORS setup is needed.
- **Production build:** static files, served by the API container. No extra hosting.
- **Scope of the first version:** chat, live status lines, and the cited answer. It is capped at two to three days of work. Slice 16, finding and deleting earlier conversations, has its own cap of one day.

## Consequences

- The app can be tested and shown in a browser from the end of Phase 1.
- The UI holds no business logic. It shows what the API sends. The same rule as the API routes.
- "Foundation" means structure: routing, one API client, one stream service, and typed models. Screens for later phases are **not** built early.
- TypeScript models mirror the Pydantic contracts by hand and live in one folder. When a contract changes, both change in the same commit. Generating them from the API schema is an option if they drift.
- Phase 3 changes the main contract from `Answer` to `Brief`. Some UI rework is expected then.
- A second toolchain: `make web-check` runs the frontend lint, tests and build. CI runs it from Phase 6.
- Charts and a visual redesign stay out of the phase plan. They can be added later without touching the API.
- The plain page planned for Phase 3 is dropped. Later phases add to the Angular app.

## In short

"I added a thin Angular front end early because it made the system easier to test and show, and I already knew the framework. It holds no logic: one API client, one stream service, typed models that mirror the back-end contracts."
