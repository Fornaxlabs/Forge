# GIT — version control standards

- MUST: at project start, create a PRIVATE GitHub repo (`gh repo create <name> --private --source . --push`) before any real work.
- MUST: use Conventional Commits (feat, fix, docs, refactor, test, chore, …).
- MUST: work on feature branches; never commit directly to main.
- MUST: open a PR for every change; CI green before merge.
- MUST: keep commits atomic — one logical change per commit.
- NEVER: force-push a shared branch.
- NEVER: commit secrets, .env files, or generated artifacts.
