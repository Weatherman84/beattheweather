.PHONY: install collect backfill dashboard test lint

install:
	python -m pip install -e '.[dev]'

collect:
	python -m weatherman.cli collect

backfill:
	python -m weatherman.cli backfill --days 365

dashboard:
	streamlit run app.py

test:
	pytest -q

lint:
	ruff check app.py src tests
