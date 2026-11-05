# Slides are written in slides/*.md; the NN-*.html decks are generated.
UV_BUILD = uv run -q --with markdown-it-py --with mdit-py-plugins --with pygments --with pyyaml
UV_PW    = uv run -q --with playwright

.PHONY: build check pdf site all
all: build check

build: ## slides/*.md -> NN-*.html
	$(UV_BUILD) python tools/build.py $(DECKS)

check: ## layout check (overlaps, overflow) for every deck, or DECKS=slides/NN-name.md / one-day/slides/NN-name.md
	$(UV_PW) python tools/check_layout.py $(patsubst one-day/slides/%.md,one-day/%.html,$(patsubst slides/%.md,%.html,$(DECKS)))

site: build ## assemble what is served from /hackathon/ into DEST (decks, one-day/ decks, assets)
	@test -n "$(DEST)" || { echo "usage: make site DEST=<dir>"; exit 2; }
	@# every source must have produced a deck, so a deck that failed to build cannot be dropped silently
	@for md in slides/[0-9]*.md; do b=$$(basename $$md .md); test -f "$$b.html" || { echo "missing deck $$b.html"; exit 1; }; done
	@for md in one-day/slides/[0-9]*.md; do b=$$(basename $$md .md); test -f "one-day/$$b.html" || { echo "missing deck one-day/$$b.html"; exit 1; }; done
	mkdir -p "$(DEST)/one-day"
	cp -R ./*.html assets "$(DEST)/"
	cp one-day/*.html "$(DEST)/one-day/"

pdf: ## one PDF per deck in pdf/
	$(UV_PW) python tools/export_pdf.py
