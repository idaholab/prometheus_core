##@
##@ Help
##@

.PHONY: help
help: ##@ (Default) Print listing of key targets with their descriptions
	@printf "\nUsage: make <command>\n"
	@grep -F -h "##@" $(MAKEFILE_LIST) | grep -Fv grep | grep -Fv 'FS =' | sed 's/\\$$//' | \
	awk 'BEGIN {FS = ":*[[:space:]]*##@[[:space:]]*"}; \
	{ \
			if($$2 == "") \
					next; \
			else if($$0 ~ /^#/) \
					printf "\n\n%s\n", $$2; \
			else if($$1 == "") \
					printf "     %-20s%s\n", "", $$2; \
			else \
					printf "\n    \033[34m%-20s\033[0m %s", $$1, $$2; \
	}'
	@printf "\n\n"

##@
##@ Checks
##@

.PHONY: lint format typecheck check fix test test-unit test-integration test-all hooks

lint: ##@ Run ruff linter (report only)
	uv run ruff check .

format: ##@ Run ruff formatter (report only)
	uv run ruff format --check .

typecheck: ##@ Run mypy type checker
	uv run mypy prometheus_api/

test: ##@ Run unit tests (default test target)
test: test-unit

test-unit: ##@ Run unit tests without integration tests
	uv run pytest -m "not integration" --cov

test-integration: ##@ Run integration tests (requires .env with DeepLynx credentials)
	uv run pytest -m integration

test-all: ##@ Run all tests, including integration tests
	uv run pytest --cov

fix: ##@ Auto-fix ruff lint issues and format
	uv run ruff check --fix .
	uv run ruff format .

check: ##@ Run all checks (lint + format + typecheck)
check: lint format typecheck

hooks: ##@ Install pre-commit and pre-push hooks
	uv run pre-commit install --hook-type pre-commit --hook-type pre-push

.PHONY: test-install
test-install: ##@ Verify package installs and imports correctly in a clean venv
	@echo "Building package..."
	@uv build --quiet
	@TMPVENV=$$(mktemp -d) && \
	uv venv --python 3.12 "$$TMPVENV" --quiet && \
	VIRTUAL_ENV="$$TMPVENV" uv pip install --quiet dist/prometheus_api-*.whl && \
	echo "Testing imports..." && \
	"$$TMPVENV/bin/python" -I -c "\
import importlib, pathlib, sys; \
packages = sorted(str(p.parent).replace('/', '.') for p in pathlib.Path('prometheus_api').rglob('__init__.py')); \
modules = [importlib.import_module(name) for name in packages]; \
outside = [m.__name__ for m in modules if not m.__file__.startswith(sys.prefix)]; \
assert not outside, f'not imported from the wheel: {outside}'; \
from prometheus_api import __version__; \
from prometheus_api.llm_configs import get_llm_config_path, list_llm_config_profiles; \
from prometheus_api.storage_client import StorageClient, AsyncStorageClient, ConnectionConfig; \
from prometheus_api.agent import PrometheusAgent; \
assert 'registry' in list_llm_config_profiles(); \
assert all(get_llm_config_path(profile).is_file() for profile in list_llm_config_profiles()); \
print(f'prometheus-api {__version__} OK ({len(packages)} packages)')" && \
	rm -rf "$$TMPVENV" dist/ *.egg-info && \
	echo "Install check passed" || \
	(rm -rf "$$TMPVENV" dist/ *.egg-info; echo "Install check FAILED"; exit 1)

##@
##@ Versioning
##@

.PHONY: version bump-patch bump-minor bump-major

version: ##@ Show current version
	@uv version --short

bump-patch: ##@ Bump patch version (0.2.0 → 0.2.1)
	@uv version --bump patch

bump-minor: ##@ Bump minor version (0.2.0 → 0.3.0)
	@uv version --bump minor

bump-major: ##@ Bump major version (0.2.0 → 1.0.0)
	@uv version --bump major

##@
##@ Container
##@

.PHONY: build-image build-local

# The Dockerfile installs CA certificates from the named "certs" build context,
# which lives outside this directory so the platform images can share it
CERTS_CONTEXT := --build-context certs=../common/certs

IMAGE_TAG ?= $(shell git rev-parse --short HEAD)

build-image: ##@ Build container images for amd64 and arm64 (IMAGE_TAG=<tag>, default: git short hash)
	docker build $(CERTS_CONTEXT) --platform linux/amd64 -t "prometheus-api:$(IMAGE_TAG)-amd64" .
	docker build $(CERTS_CONTEXT) --platform linux/arm64 -t "prometheus-api:$(IMAGE_TAG)-arm64" .
	@echo "Built prometheus-api:$(IMAGE_TAG)-amd64 and prometheus-api:$(IMAGE_TAG)-arm64"

LOCAL_IMAGE ?= prometheus_api:local
# Registry build cache to import, as <image>:<tag>. Empty builds uncached
CACHE_FROM ?=
CACHE_FROM_FLAG :=
ifneq ($(CACHE_FROM),)
# Not inline in the recipe: the comma would split the arguments of $(if)
CACHE_FROM_FLAG := --cache-from "type=registry,ref=$(CACHE_FROM)"
endif

build-local: ##@ Build a host-arch image into the local Docker store for the platform (LOCAL_IMAGE=<name:tag>, default: prometheus_api:local; CACHE_FROM=<image:tag> to import a registry cache)
	docker build $(CERTS_CONTEXT) $(CACHE_FROM_FLAG) -t "$(LOCAL_IMAGE)" .
