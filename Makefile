PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
BOT := .venv/bin/gravity-dca
DASHBOARD := .venv/bin/gravity-dca-dashboard
CONFIG ?= config.toml
SYMBOL ?= BTC_USDT_Perp
IMAGE ?= gravity-dca-bot:local
IMAGE_DASHBOARD ?= gravity-dca-dashboard:local
CONTAINER ?= gravity-dca
CONTAINER_DASHBOARD ?= gravity-dca-dashboard

.PHONY: venv install test run once instrument position-config status thresholds recovery-status notify-test dashboard docker-build dashboard-docker-build docker-run docker-once docker-up docker-restart docker-logs docker-down dashboard-docker-run dashboard-docker-up dashboard-docker-logs dashboard-docker-down clean

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

status:
	$(BOT) --config $(CONFIG) --status

thresholds:
	$(BOT) --config $(CONFIG) --thresholds

recovery-status:
	$(BOT) --config $(CONFIG) --recovery-status

notify-test:
	$(BOT) --config $(CONFIG) --notify-test

dashboard:
	$(DASHBOARD)

docker-build:
	docker build -t $(IMAGE) .

dashboard-docker-build:
	docker build -f Dockerfile.dashboard -t $(IMAGE_DASHBOARD) .

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

dashboard-docker-run:
	docker run --rm -it \
		-p 8080:8080 \
		-v /var/run/docker.sock:/var/run/docker.sock \
		$(IMAGE_DASHBOARD)

dashboard-docker-up:
	docker run -d \
		--name $(CONTAINER_DASHBOARD) \
		-p 8080:8080 \
		-v /var/run/docker.sock:/var/run/docker.sock \
		$(IMAGE_DASHBOARD)

dashboard-docker-logs:
	docker logs -f $(CONTAINER_DASHBOARD)

dashboard-docker-down:
	docker stop $(CONTAINER_DASHBOARD) || true
	docker rm $(CONTAINER_DASHBOARD) || true

clean:
	rm -rf .venv .pytest_cache
