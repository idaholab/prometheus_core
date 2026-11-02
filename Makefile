.PHONY: hooks
# pre-commit comes from sdk/uv.lock, so its version stays locked and updated by Dependabot
hooks: ##@ Install the git hooks
	uv run --directory sdk pre-commit install --config ../.pre-commit-config.yaml --hook-type pre-commit --hook-type pre-push
