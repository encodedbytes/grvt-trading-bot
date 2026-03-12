PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
BOT := .venv/bin/gravity-dca
CONFIG ?= config.toml
SYMBOL ?= BTC_USDT_Perp
IMAGE ?= gravity-dca-bot:local

.PHONY: venv install test run once instrument docker-build docker-run docker-once clean

venv:
	python3 -m venv .venv
	$(PIP) install --upgrade pip

install: venv
	$(PIP) install -e '.[dev]'

test:
	$(PYTEST)

run:
	$(BOT) --config $(CONFIG)

once:
	$(BOT) --config $(CONFIG) --once

instrument:
	$(BOT) --config $(CONFIG) --instrument $(SYMBOL)

docker-build:
	docker build -t $(IMAGE) .

docker-run:
	docker run --rm -it \
		-v $(PWD)/$(CONFIG):/app/config.toml:ro \
		-v $(PWD)/state:/state \
		$(IMAGE) --config /app/config.toml

docker-once:
	docker run --rm -it \
		-v $(PWD)/$(CONFIG):/app/config.toml:ro \
		-v $(PWD)/state:/state \
		$(IMAGE) --config /app/config.toml --once

clean:
	rm -rf .venv .pytest_cache
