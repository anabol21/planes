# Workstream status protocol

One file represents one stream. Agents must read it before work and update it before handoff. YAML keys are machine-validated by `scripts/validate_workspace.py`.

Allowed states: `planned`, `in_progress`, `blocked`, `review`, `done`.

Do not erase previous evidence. Move superseded notes into the checkpoint log if the status file becomes long.
