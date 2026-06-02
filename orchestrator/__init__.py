"""orchestrator — outreach-factory pipeline core.

This package marker lets downstream code import modules as
`from orchestrator import identity` while preserving the existing
`python orchestrator/<script>.py` script-execution pattern (script
execution puts the script's directory at sys.path[0], so sibling imports
like `import state_machine` inside enrollment.py continue to work).

The dual style is intentional:
  - Tests + future external consumers use package imports
    (`from orchestrator import identity`).
  - Existing pipeline scripts use sibling imports
    (`import state_machine`) because they're invoked as standalone
    scripts via the SKILL.md flows.

Both styles will keep working as long as orchestrator/ is on sys.path
(either because Python adds it for script execution, or because the
caller arranged it — see tests/conftest.py).
"""
