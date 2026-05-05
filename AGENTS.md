always announce when you're referencing this file.

## Python Environment

This workspace uses a shared `.venv` virtual environment at the workspace root. Always use this environment for all Python operations:

- Default interpreter: `${workspaceFolder}/.venv/Scripts/python.exe`
- When running Python scripts, the venv is auto-activated in terminals
- When installing packages, they go into the shared `.venv`

when creating plan, always

- quote the web links used to gather research in the plan document
- always think and consider edge cases, document approach accordingly
- follow best coding practices depending on language and framework
- never use parallel subagents
- dont assume, ask enough questions
- when building onto an existing system, always ensure plan is logically fitting into the existing infrastructure

after transitioning from plan to agent mode to build a plan, always

- use sequential subagents

dont use flowery language , always

- be precise and to the point
- actively counter the user to suggest better approaches

in general, always

- always use websearch and webfetch liberally to solve problems and ground your reasoning with evidence
- never use parallel subagents, always use subagents in sequence
- create atomic context files when doing lots of changes, create a map here to reference them as and when required, update them as and when needed

