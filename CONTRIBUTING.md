# Contributing

## Branching

Use one branch per task:

```text
feature/<area>-<short-description>
fix/<area>-<short-description>
docs/<short-description>
```

Examples: `feature/manager-planning`, `fix/runtime-timeout`, and
`docs/adapter-protocol`.

## Pull Requests

- Keep each pull request focused on one task.
- Link the task description and list the interfaces affected by the change.
- Include tests for behavior changes.
- Request review from the owner of any affected shared module.
- Do not push directly to `main`.

## Ownership

| Area | Owner |
| --- | --- |
| Manager Agent and planning API | A |
| Agent runtime, Git operations, and permissions | B |
| Interface registry, CLI, realtime, and frontend | C |
| Shared models, schemas, and contracts | Shared; A maintains the initial version |

Changes outside your area require agreement on the updated contract first.

## Commit Messages

Use conventional prefixes such as `feat:`, `fix:`, `test:`, `docs:`, and
`chore:`.
