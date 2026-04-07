# Main Decisions - 2026-04-07

## Decisions
- Start from a fresh scaffold instead of importing the previous Django baseline.
- Keep the architecture minimal: one Django project and one app for Sprint 1 foundation work.
- Implement the first vertical slice around session scheduling and RSVP instead of only generating boilerplate.
- Delay authentication and notifications infrastructure until the core session flow is stable.

## Implemented Scope
- Session creation
- Next session view
- RSVP submission and update
- Coach RSVP overview

## Rationale
- The assignment does not require starting from scratch, but the repo was empty and the user explicitly chose a fresh start.
- A narrow vertical slice is better for Sprint 1 than broad shallow scaffolding.
