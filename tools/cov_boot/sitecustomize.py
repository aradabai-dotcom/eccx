"""Start coverage in *subprocesses* too.

Most of the CLI surface is exercised by tests that spawn `eccx` as a child
process. Without this, cli.py reports 8% and the number lies. Set
COVERAGE_PROCESS_START=.coveragerc and put this directory on PYTHONPATH.
"""
try:
    import coverage
    coverage.process_startup()
except Exception:
    pass
