# SignalDesk Architecture

## Product decision

SignalDesk is a quality-first companion to SaaSquatch. The two headline features are explainable buy-box scoring and a multi-source data-quality pipeline. Supporting controls exist to make those features usable: filters, export, deterministic outreach drafts, insights, and ethics disclosure.

## UX choices

The first screen leads with the decision a searcher needs: which lead should be contacted first? A no-login reviewer sees a ranked synthetic dataset immediately. The five-step strip (Import, Clean, Score, Review, Export) makes the workflow legible without requiring a tutorial. Score badges, reason chips, confidence percentages, and validation states separate fit from trust. The left panel keeps the buy-box profile visible so changing one weight has an observable result.

The UI uses an original dark-sidebar/light-workspace system, lime action accent, indigo status accent, high-contrast text, keyboard-focusable controls, labels for inputs, and a responsive table. Rows are rendered through TanStack Table and TanStack Virtual so the interaction model can extend to larger datasets.

## Backend architecture

`api/index.py` is the Vercel entrypoint and exports the FastAPI `app`. The current compact implementation keeps the pipeline orchestration in `api/app/main.py`; the logical boundaries are explicit functions for normalization, dedupe, validation, scoring, discovery, and export. A future expansion can split those functions into adapters and services without changing the endpoint contract.

Adapters are isolated by endpoint: CSV parsing is deterministic and local; OpenStreetMap discovery uses Overpass with an honest User-Agent; website enrichment is represented as a reviewable queued action so the app never silently fetches or stores private personal data. A source failure returns a meaningful 502 and leaves the existing pipeline usable.

## Supabase Postgres

The schema in `supabase/schema.sql` contains `pipeline_runs`, `leads`, and `lead_change_log`. It retains raw payloads and change records so normalization and duplicate merging are explainable. Supabase is used as the persistence layer once credentials are configured. The demo does not require an account and uses bundled synthetic data when credentials are absent.

Create the Supabase project in the nearest appropriate US region and record the actual region here after setup. The service-role key is server-only. Row-level security is enabled and no public policies are added.

## Caching and performance

- Client cache: TanStack Query is configured in the frontend for API responses.
- HTTP cache: discovery responses can be given ETag and short `Cache-Control` headers when deployed behind Vercel.
- Server TTL cache: OpenStreetMap discovery is retained in memory for 15 minutes.
- Instance cache: Vercel Fluid Compute may reuse warm function instances; the application never assumes that cache is durable.
- Virtual rendering: TanStack Virtual limits DOM rows for large tables.
- Pipeline performance: normalization and scoring are linear; dedupe uses a domain/name key; outbound discovery is bounded by a limit and a timeout.

## Hosting and deployment

Vercel can host the Vite static build from `frontend/dist` and the FastAPI function from `api/index.py`. Configure the project and environment variables manually in Vercel or through your preferred Git provider workflow. Supabase migrations are run manually from the SQL Editor using the supplied script.

The target runtime is Python 3.12 because it satisfies the requested Python 3.11+ stack and is listed by current Vercel Python runtime documentation. The exact stack is React 18, Vite 6, TypeScript 5, Tailwind CSS 3, TanStack Query/Table/Virtual 5/8/3, React Router 7, FastAPI, Pydantic 2, httpx, pytest, ruff, mypy, Vercel, and Supabase Postgres.

## Resilience and ethics

The app uses timeouts, bounded result counts, cache fallback, and explicit partial-failure messaging. It does not bypass CAPTCHAs, evade IP blocks, scrape private people, or silently drop rows. Public data sources must be attributed and their terms honored.