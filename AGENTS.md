# AGENTS.md

## Project context

This repository contains host-side tooling used to support micromouse development.

Typical uses include:
- telemetry post-processing
- data cleaning and transformation
- plotting and reporting
- notebook-based exploration
- GUI tools such as maze editing
- future reusable developer tools for analysis and workflow automation

The code in this repository runs on desktop-class systems such as Windows or Linux.
It does not run on microcontrollers.

## Main goals

When proposing or implementing changes, prioritise:

1. Correctness
2. Developer productivity
3. Clear structure
4. Reproducibility
5. Ease of maintenance
6. Performance where it matters

Performance matters for larger datasets, but this repository is not firmware and does not need firmware-style constraints.

## Working modes

This repository supports two kinds of Codex interaction.

### Mode 1 — Feature/spec mode
Use this when planning or implementing larger changes.

Examples:
- building a telemetry processing tool
- converting notebook logic into reusable modules
- adding a GUI tool
- restructuring the project layout
- adding import/export/report generation features

In this mode:
- inspect the repository first
- produce or update a spec in `.ai-specs/`
- do not modify code until explicitly approved in chat
- keep open questions clearly listed in the spec

### Mode 2 — Ad hoc helper mode
Use this when the user asks for a specific snippet, plot, function, parser, or explanation in chat.

Examples:
- pandas transformations
- plotting code
- regex or parsing helpers
- notebook refactoring suggestions
- matplotlib fixes
- file format conversion helpers

In this mode:
- answer directly in chat
- provide code snippets when useful
- do not force creation of a spec unless the request is clearly a larger feature or architectural change

## Repository inspection

Before proposing larger implementation changes:
- inspect the repository
- identify relevant files, modules, functions, classes, and scripts
- cite file paths and symbols where possible
- do not guess behaviour not supported by the repository

If something is unclear, say so explicitly.

## Python project guidance

Prefer:
- small reusable functions over large notebook cells
- modules that can be imported from notebooks, scripts, or GUIs
- clear separation between data loading, processing, plotting, and UI
- configuration via explicit parameters or config objects where useful
- code that works on both Windows and Linux where practical

When relevant, consider:
- path handling
- file formats
- reproducibility
- batch processing
- user workflow ergonomics

## Notebook guidance

Notebooks are allowed and useful for exploration.

However, when notebook logic becomes:
- repetitive
- order-dependent
- reused across sessions
- difficult to rerun cleanly

prefer extracting that logic into normal Python modules or scripts.

Notebook cells should ideally become thin orchestration layers over reusable functions.

## Implementation safety

Do not modify code unless explicitly approved in chat.

For larger changes:
- create/update a spec first
- do not implement while open questions remain
- implement only after explicit approval

For small ad hoc requests:
- code snippets in chat are fine
- direct file edits are still not allowed unless explicitly requested


## Spec format

Spec files live in:

`.ai-specs/`

Each spec should contain:

1. Summary
2. Current repository findings
3. Proposed change
4. Implementation plan
5. Risks and constraints
6. Open questions
7. Approval boundary

Keep specs concise, practical, and implementation-oriented.

## Output style

- Be concrete and useful
- Prefer practical engineering detail over generic advice
- Keep docs lightweight
- For larger changes, produce a clear implementation path
- For small questions, provide direct answers and usable code