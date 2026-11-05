# Slides are written in slides/*.md; the NN-*.html decks are generated.
UV_BUILD = uv run -q --with markdown-it-py --with mdit-py-plugins --with pygments --with pyyaml
UV_PW    = uv run -q --with playwright

.PHONY: build check pdf all
all: build check

build: ## slides/*.md -> NN-*.html
	$(UV_BUILD) python tools/build.py $(DECKS)

check: ## layout check (overlaps, overflow) for every deck, or DECKS=slides/NN-name.md / one-day/slides/NN-name.md
	$(UV_PW) python tools/check_layout.py $(patsubst one-day/slides/%.md,one-day/%.html,$(patsubst slides/%.md,%.html,$(DECKS)))

pdf: ## one PDF per deck in pdf/
	$(UV_PW) python tools/export_pdf.py
