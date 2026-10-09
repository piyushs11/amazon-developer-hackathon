# Contributing

- Branch from `main`: `feat/<lane>-<short-name>` (lanes: catalog, codegen, auth, ui)
- No direct commits to `main`
- Small PRs (~300 lines), 1 review, squash merge
- Rebase on `main` daily
- Stay in your own folders (see CODEOWNERS)
- `contracts/` changes: separate PR, all 4 approve, update fixtures in the same PR
- Never commit `.env`, tokens or secrets
