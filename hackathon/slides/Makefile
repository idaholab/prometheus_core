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
	mkdir -p "$(DEST)/one-day"
	cp -R ./*.html assets "$(DEST)/"
	cp one-day/*.html "$(DEST)/one-day/"

pdf: ## one PDF per deck in pdf/
	$(UV_PW) python tools/export_pdf.py
