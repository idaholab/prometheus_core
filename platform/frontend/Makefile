##@
##@ Frontend React
##@

.PHONY: dev build lint format format-check typecheck test test-e2e test-e2e-full check install

dev: ##@ Start Vite dev server
	npm run dev -- --port 5150

build: ##@ Build for production
	npm run build

lint: ##@ Run eslint
	npm run lint

format: ##@ Format the code with Prettier
	npm run format

format-check: ##@ Fail if any file isn't formatted with Prettier
	npm run format:check

typecheck: ##@ Run TypeScript type checker
	npm run typecheck

test: ##@ Run the unit and component tests (vitest)
	npm test

test-e2e: ##@ Run the end-to-end tests (Playwright, headless Chromium)
	npm run test:e2e

test-e2e-full: ##@ Run the end-to-end tests against the e2e stack (start the stack first: make up-e2e in platform/)
	npm run test:e2e:full

check: ##@ Run format-check + lint + typecheck + test; the end-to-end tests are separate (make test-e2e)
check: format-check lint typecheck test

install: ##@ Install dependencies
	npm install
	