# Prometheus Platform — Makefile
#
# Specialist agents live in agents/*/docker-compose.yml.
# Any agent directory that contains a docker-compose.yml is included automatically.
# To exclude an agent, remove its directory.

# Load variables from .env if present (no error if missing). Lets settings like
# DEBUG_AGENTS live alongside the rest of the project config.
-include .env

COMPOSE_PROJECT_NAME ?= prometheus_platform
export COMPOSE_PROJECT_NAME

COMPOSE := docker compose -p $(COMPOSE_PROJECT_NAME)

COMPOSE_BASE   := docker-compose.yml
COMPOSE_AGENTS := docker-compose.agents.yml

# Set LOCAL_SDK=true (in .env or on the command line) to build the
# prometheus_api base image from ../sdk into the local Docker store and build
# all services FROM it, instead of pulling the published image. Use it to run
# against the SDK checked out in ../sdk. Default: false.
LOCAL_SDK ?= false

ifeq ($(LOCAL_SDK),true)
PROMETHEUS_API_BASE_IMAGE_REPO := prometheus_api
PROMETHEUS_API_BASE_IMAGE_HASH := local
BASE_IMAGE_DEP := base-image
else
# Override these to pin a specific prometheus_api base image. The default is
# the SDK image that publish-images pushes to ghcr.io; its tags are
# <commit date>-<7 char sha>. Keep in step with platformctl's
# DEFAULT_BASE_IMAGE_* in ctl/platformctl/config.py.
PROMETHEUS_API_BASE_IMAGE_REPO ?= ghcr.io/idaholab/prometheus_core/prometheus_sdk-devel
PROMETHEUS_API_BASE_IMAGE_HASH ?= 20261031-b999096
BASE_IMAGE_DEP :=
endif
export PROMETHEUS_API_BASE_IMAGE_REPO
export PROMETHEUS_API_BASE_IMAGE_HASH

# Set DEBUG_AGENTS=true (in .env or on the command line) to also include
# agents/debug-agents/*/docker-compose.yml (one extra directory level deep).
# Default: false.
DEBUG_AGENTS ?= false

# Set OPTIONAL_AGENTS=true to also include agents/optional/*/docker-compose.yml:
# heavy agents most setups don't need (OSTI research pulls in PDF/ML
# dependencies and dominates the build time). Default: false.
OPTIONAL_AGENTS ?= false

# Set LOCAL_DEEPLYNX=true to also run DeepLynx (docker-compose.deeplynx.yml)
# from its published images, and point the platform at it: every start target
# first starts DeepLynx and runs `make deeplynx-setup`, which writes the
# DEEPLYNX_* settings to .env. Its web UI is at http://localhost:3000.
# Default: false.
LOCAL_DEEPLYNX ?= false
DEEPLYNX_SERVER_PORT ?= 5000
DEEPLYNX_DEP := $(if $(filter true,$(LOCAL_DEEPLYNX)),deeplynx-setup,)

# Publish the client-agent port for host-driven full-system tests without
# changing the runtime API surface. The system-test suite itself never starts
# or reconfigures Docker.
PROMETHEUS_SYSTEM_TESTING ?= false
CLIENT_AGENT_PORT ?= 8001
PROMETHEUS_SYSTEM_TEST_URL ?= http://localhost:$(CLIENT_AGENT_PORT)

# Set PROFILE=prod to bring up the React frontend in production mode instead,
# or PROFILE= (empty) to exclude the React frontend entirely. Default: dev.
PROFILE ?= dev
PROFILE_FLAGS := $(if $(PROFILE),--profile $(PROFILE),)

# Extra flags for `docker compose up` in `make up`.
UP_ARGS ?=

# The detached start targets (up, restart, ng-up, ng-restart) wait for every
# service with a healthcheck to report healthy (`docker compose up --wait`),
# then run `make check`. Set CHECK=false to return as soon as the containers
# are started instead.
CHECK ?= true
WAIT_TIMEOUT ?= 600
CHECK_TIMEOUT ?= 300
UP_WAIT := $(if $(filter true,$(CHECK)),--wait --wait-timeout $(WAIT_TIMEOUT),)
RUN_CHECK := $(if $(filter true,$(CHECK)),$(MAKE) --no-print-directory check,)

# Host ports that `make check` probes. The defaults must match the ones in the
# ports of backend, frontend-dev and frontend-prod in docker-compose.yml.
BACKEND_PORT ?= 8600
FRONTEND_DEV_PORT ?= 5150
FRONTEND_PROD_PORT ?= 8080
FRONTEND_PORT := $(if $(filter dev,$(PROFILE)),$(FRONTEND_DEV_PORT),$(if $(filter prod,$(PROFILE)),$(FRONTEND_PROD_PORT),))

# All per-agent compose files found on disk (checked-out submodules only).
AGENT_COMPOSE_FILES := $(shell find agents -mindepth 2 -maxdepth 2 -name docker-compose.yml 2>/dev/null | sort)
ifeq ($(DEBUG_AGENTS),true)
AGENT_COMPOSE_FILES += $(shell find agents/debug-agents -mindepth 2 -maxdepth 2 -name docker-compose.yml 2>/dev/null | sort)
endif
ifeq ($(OPTIONAL_AGENTS),true)
AGENT_COMPOSE_FILES += $(shell find agents/optional -mindepth 2 -maxdepth 2 -name docker-compose.yml 2>/dev/null | sort)
endif

# Build the -f flags for docker compose.
COMPOSE_FILES := -f $(COMPOSE_BASE)
ifeq ($(PROMETHEUS_SYSTEM_TESTING),true)
COMPOSE_FILES += -f docker-compose.system-test.yml
endif
ifneq ($(AGENT_COMPOSE_FILES),)
COMPOSE_FILES += -f $(COMPOSE_AGENTS)
endif
ifeq ($(LOCAL_DEEPLYNX),true)
COMPOSE_FILES += -f docker-compose.deeplynx.yml
endif
# Automatically include docker-compose.override.yml if present (local dev overrides).
ifneq ($(wildcard docker-compose.override.yml),)
COMPOSE_FILES += -f docker-compose.override.yml
endif

# No-generate compose flags: include agents compose only if it already exists on disk.
COMPOSE_FILES_NG := -f $(COMPOSE_BASE)
ifeq ($(PROMETHEUS_SYSTEM_TESTING),true)
COMPOSE_FILES_NG += -f docker-compose.system-test.yml
endif
ifneq ($(wildcard $(COMPOSE_AGENTS)),)
COMPOSE_FILES_NG += -f $(COMPOSE_AGENTS)
endif
ifeq ($(LOCAL_DEEPLYNX),true)
COMPOSE_FILES_NG += -f docker-compose.deeplynx.yml
endif
ifneq ($(wildcard docker-compose.override.yml),)
COMPOSE_FILES_NG += -f docker-compose.override.yml
endif

# The builds of the sdk base image, backend and frontend import the registry
# cache that publish-images writes. BUILD_CACHE is its prefix (one package per
# image); a fork can point it at its own. The tag is the host's platform. The
# agent images aren't published, so they build uncached. Importing a registry
# cache needs the containerd image store (Docker Desktop's default). Set
# USE_BUILD_CACHE=false (in .env or on the command line) to build without it,
# e.g. when offline. Default: true.
USE_BUILD_CACHE ?= true
BUILD_CACHE ?= ghcr.io/idaholab/prometheus_core/buildcache-prometheus
ifeq ($(USE_BUILD_CACHE),true)
BUILD_CACHE_PLATFORM ?= $(if $(filter arm64 aarch64,$(shell uname -m)),arm64,amd64)
export BUILD_CACHE
export BUILD_CACHE_PLATFORM
COMPOSE_FILES += -f docker-compose.build-cache.yml
COMPOSE_FILES_NG += -f docker-compose.build-cache.yml
endif

CLEAR_COMPOSE_FILES ?= $(COMPOSE_FILES_NG)

##@
##@ Help
##@

.PHONY: help
help: ##@ (Default) Print listing of key targets with their descriptions
	@printf "\nUsage: make <command>\n"
	@grep -F -h "##@" $(MAKEFILE_LIST) | grep -F -v grep -F | sed -e 's/\\$$//' | awk 'BEGIN {FS = ":*[[:space:]]*##@[[:space:]]*"}; \
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
##@ Prerequisites
##@

# Shared with the repo-root infrastructure/ (local k3d cluster).
INFRA_SCRIPTS := ../infrastructure/scripts

.PHONY: check-prerequisites
check-prerequisites: ##@ Verify Docker before running platform tasks
	@SKIP_PREREQUISITES=$(SKIP_PREREQUISITES) $(INFRA_SCRIPTS)/check-local-prereqs.sh --compose

# These targets require the platform runtime prerequisites. Static tests,
# frontend-only tasks, help, and compose-file generation are intentionally
# excluded because they do not require certificates or Docker.
PREREQUISITE_TARGETS := \
	test-integration \
	test-infra \
	up \
	up-fg \
	restart \
	restart-fg \
	ng-up \
	ng-up-fg \
	ng-restart \
	ng-restart-fg \
	clear-agent-registry \
	deeplynx-setup \
	down \
	down-v \
	base-image \
	build \
	build-plain \
	logs \
	ps

$(PREREQUISITE_TARGETS): check-prerequisites

.PHONY: all up up-fg down down-v build base-image build-plain logs ps generate clean-generated regenerate restart restart-fg ng-up ng-up-fg ng-restart ng-restart-fg init-env clear-agent-registry deeplynx-setup clear-admin-users clobber help

FORCE:

## Generate the agents compose file from discovered agent compose files.
generate: $(COMPOSE_AGENTS)

# Generate a merged compose file with project-root-relative paths and shared
# build args. Docker Compose YAML anchors do not cross included files.
$(COMPOSE_AGENTS): FORCE $(AGENT_COMPOSE_FILES)
	@echo "# Auto-generated by 'make generate' - do not edit by hand."> $@
	@echo "# Re-run 'make generate' after checking out or removing agent submodules." >> $@
	@echo "" >> $@
	@echo "include:" >> $@
	@for f in $(AGENT_COMPOSE_FILES); do echo "  - $$f"; done >> $@
	@echo "Generated $(COMPOSE_AGENTS) with $(words $(AGENT_COMPOSE_FILES)) agent(s):"
	@for f in $(AGENT_COMPOSE_FILES); do echo "  $$f"; done

##@
##@ Tests
##@

.PHONY: test-static test-integration test-infra test-system

test-static: ##@ Run static infrastructure tests (no Docker needed)
	cd tests && uv run python -m pytest -m "not integration" -v

test-integration: ##@ Run integration tests (containers must be running)
	cd tests && uv run python -m pytest -m integration -v

test-infra: ##@ Run all infrastructure tests
	cd tests && uv run python -m pytest -v

.PHONY: check-markings
check-markings: ##@ Fail if a tracked .py/.ts/.tsx/.jsx file lacks the copyright marking
	python3 scripts/add_markings.py --check

test-system: export AGENT_SECRET := $(AGENT_SECRET)
test-system: export LLM_CONFIG_PROFILE := $(LLM_CONFIG_PROFILE)
test-system: export LLM_API_KEY := $(LLM_API_KEY)
test-system: export EMBEDDING_API_KEY := $(EMBEDDING_API_KEY)
test-system: export DEEPLYNX_BASE_URL := $(DEEPLYNX_BASE_URL)
test-system: export DEEPLYNX_KEY := $(DEEPLYNX_KEY)
test-system: export DEEPLYNX_SECRET := $(DEEPLYNX_SECRET)
test-system: export DEEPLYNX_ORG_ID := $(DEEPLYNX_ORG_ID)
test-system: export DEEPLYNX_PROJECT_ID := $(DEEPLYNX_PROJECT_ID)
test-system: export PROMETHEUS_SYSTEM_TEST_URL := $(PROMETHEUS_SYSTEM_TEST_URL)
test-system: ##@ Test the user experience on an already-running platform (start with PROMETHEUS_SYSTEM_TESTING=true)
	cd tests && uv run python -m pytest -m system system -v

# The agents come from the generated compose file at run time, so the ng-*
# targets check the agents they actually started.
.PHONY: check
check: ##@ Wait until the running platform answers on its host ports and every agent is registered with the backend
	python3 -u scripts/check_platform.py --timeout $(CHECK_TIMEOUT) \
		--backend-port $(BACKEND_PORT) \
		$(if $(FRONTEND_PORT),--frontend-port $(FRONTEND_PORT),) \
		agents/client-agent $$(sed -n 's#^  - \(.*\)/docker-compose.yml$$#\1#p' $(COMPOSE_AGENTS) 2>/dev/null)

##@
##@ Compose
##@

up: ##@ Clear agent registrations, build and start all services (detached), then wait until they are up (CHECK=false to skip). Set PROFILE=dev|prod to include the React frontend.
up: CLEAR_COMPOSE_FILES := $(COMPOSE_FILES) $(PROFILE_FLAGS)
up: $(BASE_IMAGE_DEP) generate init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) up --build -d $(UP_WAIT) $(UP_ARGS)
	$(RUN_CHECK)

up-fg: ##@ Clear agent registrations, then build and start all services (foreground). Set PROFILE=dev|prod to include the React frontend.
up-fg: CLEAR_COMPOSE_FILES := $(COMPOSE_FILES) $(PROFILE_FLAGS)
up-fg: $(BASE_IMAGE_DEP) generate init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) up --build

restart: ##@ Clear agent registrations, then restart all services without rebuilding.
restart: CLEAR_COMPOSE_FILES := $(COMPOSE_FILES) $(PROFILE_FLAGS)
restart: generate init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) up -d $(UP_WAIT)
	$(RUN_CHECK)

restart-fg: ##@ Clear agent registrations, then restart all services without rebuilding (foreground).
restart-fg: CLEAR_COMPOSE_FILES := $(COMPOSE_FILES) $(PROFILE_FLAGS)
restart-fg: generate init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) up

ng-up: ##@ Clear agent registrations, then start without regenerating agents compose.
ng-up: $(BASE_IMAGE_DEP) init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES_NG) $(PROFILE_FLAGS) up --build -d $(UP_WAIT)
	$(RUN_CHECK)

ng-up-fg: ##@ Clear agent registrations, then start without regenerating (foreground).
ng-up-fg: $(BASE_IMAGE_DEP) init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES_NG) $(PROFILE_FLAGS) up --build

ng-restart: ##@ Clear agent registrations, then restart without rebuilding or regenerating.
ng-restart: init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES_NG) $(PROFILE_FLAGS) up -d $(UP_WAIT)
	$(RUN_CHECK)

ng-restart-fg: ##@ Clear agent registrations, then restart without rebuilding or regenerating (foreground).
ng-restart-fg: init-env clear-agent-registry $(DEEPLYNX_DEP)
	$(COMPOSE) $(COMPOSE_FILES_NG) $(PROFILE_FLAGS) up

init-env: ##@ Create .env from .env.example if missing, generate blank secrets, check the LLM API key
	@python3 scripts/init_env.py

# Agents register with the backend at startup and the registry lives in Valkey,
# which persists across restarts. Clearing it on every launch keeps an agent that
# was removed (or renamed) from lingering as a tool. Valkey must be up to clear
# it, so this starts only redis; the start target that follows reuses it.
clear-agent-registry: ##@ Stop services and delete only the agent registrations from Valkey
	$(COMPOSE) $(CLEAR_COMPOSE_FILES) down --remove-orphans
	$(COMPOSE) $(CLEAR_COMPOSE_FILES) up -d redis
	@$(COMPOSE) $(CLEAR_COMPOSE_FILES) exec -T redis sh -c '\
		cli="valkey-cli --no-auth-warning -a $$REDIS_PASSWORD"; \
		for i in $$(seq 1 30); do $$cli ping >/dev/null 2>&1 && break; sleep 1; done; \
		printf "Cleared %s agent registration key(s).\n" "$$($$cli DEL prometheus:agent-registry)"'

# The agents read DEEPLYNX_* when they start, so DeepLynx has to be up and its
# key in .env before the rest of the stack starts. Only the DeepLynx services
# start here, from just the files they need, so the ng-* targets still don't
# regenerate the agents compose file; the start target that follows reuses them.
deeplynx-setup: init-env
deeplynx-setup: ##@ Start the local DeepLynx (LOCAL_DEEPLYNX=true) and save a project and API key for it in .env
	@if [ "$(LOCAL_DEEPLYNX)" != true ]; then \
		printf "LOCAL_DEEPLYNX is not true; set it (in .env or on the command line) to run DeepLynx locally.\n"; \
		exit 1; \
	fi
	$(COMPOSE) -f $(COMPOSE_BASE) -f docker-compose.deeplynx.yml up -d --wait --wait-timeout $(WAIT_TIMEOUT) deeplynx-postgres deeplynx-server deeplynx-ui
	@python3 scripts/deeplynx_setup.py --port $(DEEPLYNX_SERVER_PORT)

clear-admin-users: ##@ Delete all rows from admin-db's users table (re-triggers the first-run setup wizard)
	@if ! $(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) ps --status running --services 2>/dev/null | grep -qx admin-db; then \
		printf "admin-db is not running; start the platform first ('make up') before running this target.\n"; \
		exit 1; \
	fi
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) exec -T admin-db psql -U admin -d admin -c "TRUNCATE TABLE users;"
	@printf "Deleted all rows from admin-db's users table -- the platform will show the first-run setup wizard again.\n"

# Volumes whose contents are tied to secrets generated into .env: admin-db's
# Postgres data dir (its password is fixed at first init, admin rows are
# encrypted with ADMIN_DB_ENCRYPTION_KEY) and Valkey (sessions and history of
# users that live in admin-db). Caches (mesh-cache, model caches) are kept.
CLOBBER_VOLUMES := admin-db-data valkey-data

clobber: ##@ Stop services and delete the DB and Valkey volumes (users, keys, history). For reinstalling after .env was lost.
	@printf "This deletes ALL users, signing keys, OIDC config, and chat history of\n"
	@printf "compose project '%s' (volumes: %s).\n" "$(COMPOSE_PROJECT_NAME)" "$(CLOBBER_VOLUMES)"
	@printf "The setup wizard runs again on the next 'make up'. Type 'clobber' to confirm: "; \
	read answer; \
	if [ "$$answer" != "clobber" ]; then printf "Aborted.\n"; exit 1; fi
	$(COMPOSE) $(COMPOSE_FILES_NG) $(PROFILE_FLAGS) down --remove-orphans
	@set -e; \
	for v in $(CLOBBER_VOLUMES); do \
		volume=$$(docker volume ls -q \
			--filter "label=com.docker.compose.project=$(COMPOSE_PROJECT_NAME)" \
			--filter "label=com.docker.compose.volume=$$v"); \
		if [ -n "$$volume" ]; then \
			docker volume rm -f $$volume; \
		else \
			printf "Volume %s does not exist; nothing to remove.\n" "$$v"; \
		fi; \
	done

down: ##@ Stop all services
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) down

down-v: ##@ Stop all services and remove volumes
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) down -v

base-image: ##@ Build the prometheus_api base image from ../sdk (automatic before builds when LOCAL_SDK=true)
	$(MAKE) -C ../sdk build-local LOCAL_IMAGE=$(PROMETHEUS_API_BASE_IMAGE_REPO):$(PROMETHEUS_API_BASE_IMAGE_HASH) \
		$(if $(filter true,$(USE_BUILD_CACHE)),CACHE_FROM=$(BUILD_CACHE)_sdk-devel:$(BUILD_CACHE_PLATFORM))

build: ##@ Build images without starting
build: $(BASE_IMAGE_DEP) generate
	$(COMPOSE) $(COMPOSE_FILES) $(PROFILE_FLAGS) build

build-plain: ##@ Build images with plain (verbose) progress output
build-plain: $(BASE_IMAGE_DEP) generate
	$(CONTAINER_RUNTIME) $(COMPOSE_FILES) $(PROFILE_FLAGS) build --progress=plain

logs: ##@ Tail logs for all services (SERVICE=<name> to filter)
	$(COMPOSE) $(COMPOSE_FILES) logs -f $(SERVICE)

ps: ##@ Show running service status
	$(COMPOSE) $(COMPOSE_FILES) ps

clean-generated: ##@ Remove the generated agents compose file.
	rm -f $(COMPOSE_AGENTS)

regenerate: ##@ Regenerate the agents compose file
regenerate: clean-generated generate

##@
##@ Local Kubernetes cluster (k3d)
##@

.PHONY: cluster-up cluster-down cluster-reset

cluster-up: ##@ Create (or start) the local k3d cluster with its image registry on localhost:5001
	@SKIP_PREREQUISITES=$(SKIP_PREREQUISITES) $(INFRA_SCRIPTS)/check-local-prereqs.sh --cluster
	@$(INFRA_SCRIPTS)/cluster-up.sh

cluster-down: ##@ Delete the local k3d cluster and its registry (pushed images are lost)
	k3d cluster delete prometheus

cluster-reset: ##@ Delete and recreate the local k3d cluster
	@$(MAKE) --no-print-directory cluster-down
	@$(MAKE) --no-print-directory cluster-up

##@
##@ Frontend (React)
##@

.PHONY: react-dev react-build react-check

react-dev: ##@ Run React frontend dev server on host, no Docker (frontend/)
	$(MAKE) -C frontend dev

react-build: ##@ Build React frontend for production (frontend/)
	$(MAKE) -C frontend build

react-check: ##@ Run React frontend lint + typecheck (frontend/)
	$(MAKE) -C frontend check
