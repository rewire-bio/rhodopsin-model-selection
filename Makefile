.PHONY: test setup data smoke reproduce analysis paper

setup:
	uv venv --python 3.11 companion/.venv
	uv pip install --python companion/.venv/bin/python -r companion/requirements-locked.txt
	uv pip install --python companion/.venv/bin/python --no-deps -e companion

test:
	companion/.venv/bin/python -m pytest companion/tests -q

# Harness execution and manuscript completion remain explicitly pending.
data smoke reproduce analysis paper:
	@echo 'Study harness/manuscript pending; use companion/README.md. No full reproduction is claimed.' >&2
	@exit 1
