# 🔐 Feature Login — Implementation Plan

> Goal: make Grain login and Telegram bot authorization reliable, one-time, and easy to link from the web dashboard.

## Legend

```text
[ ] = Not started
[~] = In progress
[x] = Complete
```

## 0.0 — Login Architecture

- [x] **0.0** — Keep dashboard auth on a signed session token and use Telegram as a linked channel rather than the primary identity source
  `Completed: 2026-05-29`

- [x] **0.1** — Add a one-time Telegram link token that is bound to a single Grain user and expires quickly
  `Completed: 2026-05-29`

- [x] **0.2** — Generate an `Open in Telegram` URL from the backend so the user can jump straight into the bot with the token attached
  `Completed: 2026-05-29`

- [x] **0.3** — Consume `/start <token>` in the Telegram webhook and mark the token as used after linking
  `Completed: 2026-05-29`

- [x] **0.4** — Block bot commands until the Telegram chat is linked to an existing Grain user
  `Completed: 2026-05-29`

- [x] **0.5** — Add a dashboard action to create the link token and launch Telegram
  `Completed: 2026-05-29`

- [x] **0.6** — Add regression tests for token generation and link validation
  `Completed: 2026-05-29`
