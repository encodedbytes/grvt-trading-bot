PYTHON := .venv/bin/python
PIP := .venv/bin/pip
PYTEST := .venv/bin/pytest
BOT := .venv/bin/gravity-dca
CONFIG ?= config.toml
SYMBOL ?= BTC_USDT_Perp

.PHONY: venv install test run once instrument clean

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

clean:
	rm -rf .venv .pytest_cache
