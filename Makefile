.PHONY: test setup data smoke reproduce analysis paper

setup:
	uv venv --python 3.11 companion/.venv
	uv pip install --python companion/.venv/bin/python -r companion/requirements-locked.txt
	uv pip install --python companion/.venv/bin/python --no-deps -e companion

test:
	companion/.venv/bin/python -m pytest companion/tests -q

# Scientific harness execution and independent reproduction remain pending.
data smoke reproduce analysis:
	@echo 'Scientific harness/reproduction pending; use companion/README.md. Historical paper is complete.' >&2
	@exit 1

paper:
	uv run --frozen python scripts/build_paper.py
