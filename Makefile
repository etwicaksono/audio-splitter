# Windows repository commands, compatible with GNU Make 3.81 and newer.
.DEFAULT_GOAL := help
.NOTPARALLEL:

POWERSHELL ?= powershell.exe
VENV ?= .venv
PYTHON ?=
MODEL ?= small
BUNDLE_MODEL ?=

MANAGE = "$(POWERSHELL)" -NoProfile -ExecutionPolicy Bypass -File "scripts/repo.ps1" -Venv "$(VENV)" $(if $(strip $(PYTHON)),-Python "$(PYTHON)",)

.PHONY: help setup install run test lint check build model doctor clean

help:
	@$(MANAGE) -Task help

setup:
	@$(MANAGE) -Task setup

install: setup
	@$(MANAGE) -Task install

run:
	@$(MANAGE) -Task run

test:
	@$(MANAGE) -Task test

lint:
	@$(MANAGE) -Task lint

check: lint test

build:
	@$(MANAGE) -Task build $(if $(strip $(BUNDLE_MODEL)),-BundleModel "$(BUNDLE_MODEL)",)

model:
	@$(MANAGE) -Task model -Model "$(MODEL)"

doctor:
	@$(MANAGE) -Task doctor

clean:
	@$(MANAGE) -Task clean
