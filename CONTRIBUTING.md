# Contributing

## Language
All code, identifiers, commit messages, comments, and documentation must be written in **English** — regardless of the contributor's native language. This keeps the codebase accessible to the whole team and consistent with libraries, tooling, and error messages, which are English by default.

## Naming
- Use clear, descriptive names (`userCount`, not `uc`).
- Avoid abbreviations unless they are widely established (`id`, `idx`, `ctx`).
- Follow the casing convention of the language in use (e.g. `camelCase` in JS/TS, `snake_case` in Python) — don't mix styles within the same codebase.

## Comments
Code should explain **what** it does through clear structure and naming. Comments should explain **why**, not what.

- Avoid comments that restate the code (`i++; // increment i`).
- Do add a comment when the reasoning isn't obvious from the code itself — e.g. a workaround, a non-obvious constraint, or an assumption behind a calculation.
- Public functions/APIs should have a short docstring describing purpose, parameters, and return value.

## Functions
- Keep functions short and single-purpose. If you can't summarize what a function does in one sentence, consider splitting it.
- Prefer early returns over deep nesting.

## Formatting
- Formatting is enforced by the linter/formatter configured for this project (see `.editorconfig` / lint config), not by manual review. Run it before committing.

## Commits
- Write commit messages in English, in the imperative mood ("Fix bug", not "Fixed bug" or "Fixes bug").
- Follow [Conventional Commits](https://www.conventionalcommits.org/) if the project uses them (e.g. `fix:`, `feat:`, `docs:`).
