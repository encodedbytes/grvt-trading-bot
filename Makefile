PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
BOT := .venv/bin/gravity-dca
CONFIG ?= config.toml
SYMBOL ?= BTC_USDT_Perp
IMAGE ?= gravity-dca-bot:local
CONTAINER ?= gravity-dca

.PHONY: venv install test run once instrument position-config thresholds recovery-status notify-test docker-build docker-run docker-once docker-up docker-restart docker-logs docker-down clean

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

position-config:
	$(BOT) --config $(CONFIG) --position-config

thresholds:
	$(BOT) --config $(CONFIG) --thresholds

recovery-status:
	$(BOT) --config $(CONFIG) --recovery-status

notify-test:
	$(BOT) --config $(CONFIG) --notify-test

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

docker-up:
	mkdir -p state
	docker run -d \
		--name $(CONTAINER) \
		-v $(PWD)/$(CONFIG):/app/config.toml:ro \
		-v $(PWD)/state:/state \
		$(IMAGE) --config /app/config.toml

docker-restart:
	mkdir -p state
	docker stop $(CONTAINER) || true
	docker rm $(CONTAINER) || true
	docker run -d \
		--name $(CONTAINER) \
		-v $(PWD)/$(CONFIG):/app/config.toml:ro \
		-v $(PWD)/state:/state \
		$(IMAGE) --config /app/config.toml

docker-logs:
	docker logs -f $(CONTAINER)

docker-down:
	docker stop $(CONTAINER) || true
	docker rm $(CONTAINER) || true

clean:
	rm -rf .venv .pytest_cache
