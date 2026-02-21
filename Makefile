.PHONY: install run smoke docker-build

install:
	pip install -r requirements.txt

run:
	streamlit run app.py

smoke:
	python scripts/smoke_test.py

docker-build:
	docker build -t sargassum-model:latest .
