ingest:
	PYTHONPATH=src python3 src/lva/ingest.py
run:
	PYTHONPATH=src python3 src/lva/pipeline.py
test:
	PYTHONPATH=src python3 -m pytest -q tests
