# Prometheus hackathon slides

Slide decks for the Prometheus agent developer hackathon (Day 1 sessions, the Day 2
challenge, judging) plus a one-page cheat sheet. Open `index.html` in a browser to
start.

## What is where

| Path | What |
|---|---|
| `slides/NN-name.md` | **The slide sources. Edit these.** Syntax: [`slides/README.md`](slides/README.md) |
| `NN-name.html` | Generated decks, one per `.md`. Not committed (git ignores them): `make build` creates them, CI builds them for the Pages site, and a pull request's `hackathon-slides` artifact has them. Don't edit |
| `index.html` | Landing page. The deck list between `<!-- decks:start -->` and `<!-- decks:end -->` is generated; the rest is hand-written |
| `cheatsheet.html` | One-page Day 2 reference (hand-written HTML, not a deck) |
| `challenge/` | The Day 2 challenge brief and practice files handed to participants |
| `one-day/` | A second, independent set of decks for the one-day format (no teams). Same layout as this folder: `slides/NN-name.md` sources, generated `NN-name.html`, its own `index.html`, and `challenge/`. It loads this folder's `assets/` through `../assets` |
| `assets/` | `deck.css` (styles), `deck.js` (slide engine), logos and images |
| `tools/` | Build, layout check, PDF export, comparison and conversion scripts |
| `pdf/` | Exported PDFs (generated, not committed) |

## Requirements

- [uv](https://docs.astral.sh/uv/): every tool runs through `uv run`, so there is no virtualenv to manage.
- Google Chrome: the layout check and the PDF export drive it through Playwright.
- GNU make (optional): the commands below work without it too.

## Editing a deck

1. Edit `slides/NN-name.md`. A slide is a block between `---` lines:

   ```markdown
   ## Run, register, check {eyebrow="Running it"}
   > One sentence under the heading.

   ::: cols 1.35fr 1fr
   ```bash
   make up
   ```
   |||
   - The agent registers itself at startup.
   :::
   ```

2. Build the HTML:

   ```bash
   make build                                   # all decks, plus the index deck list
   make build DECKS=slides/04-agent-template.md # one deck
   ```

3. Check the layout. It must report `TOTAL ISSUES: 0` (no overlapping text, nothing running off the slide):

   ```bash
   make check
   ```

4. Look at it: open the deck in a browser and reload.
5. Commit the `.md`. The decks are not committed. `make build` also refreshes the deck list in `index.html`; commit that file if it changed.

Without make:

```bash
uv run -q --with markdown-it-py --with mdit-py-plugins --with pygments --with pyyaml python tools/build.py
uv run -q --with playwright python tools/check_layout.py
```

### Conventions

- Content is sized automatically: each slide's content is scaled (zoom 0.8–1.45) to fill the space above the footer. If the check reports `AUTOFIT-SHRUNK`, the slide is too full: cut text or split it.
- The talk comes first. **Bonus** slides (catch-up help) and the **appendix** (reference material skipped in the talk) follow, each started by a section heading with `.bonus` or `.appendix`. Appendix slides are numbered "A n / m".
- Speaker notes are written as `Note: …` paragraphs.
- Anything the Markdown syntax can't express can be written as raw HTML in the `.md` file; see the end of [`slides/README.md`](slides/README.md).

### Adding a deck

1. Create `slides/NN-name.md` with the front matter (`title`, `footer`, `accent`, `index`). Copy the header of an existing deck.
2. Run `make build`. The deck appears in `index.html` automatically.

## Presenting

In a deck:

| Key | Action |
|---|---|
| `→` / `Space` | next slide |
| `←` | previous slide |
| `Home` / `End` | first / last slide |
| `O` | overview of all slides |
| `A` | jump to the appendix |
| `N` | show speaker notes |
| `F` | fullscreen |
| `I` | back to the index |

Slides are a fixed 1600×900 stage scaled to the window. For a PDF backup:

```bash
make pdf          # one PDF per deck in pdf/, one slide per page
```

## Tools

| Script | Purpose |
|---|---|
| `tools/build.py` | Markdown → HTML decks and the index deck list, for this folder and `one-day/` |
| `tools/check_layout.py` | Overlap/overflow check; `--shots DIR` also saves a PNG per slide |
| `tools/export_pdf.py` | PDF export |
| `tools/sheet.py` | Contact sheets (3×3) from screenshots, for a quick visual review |
| `tools/compare.py` | Text and pixel differences between two versions of a deck |
| `tools/html2md.py` | The one-time HTML → Markdown converter used for the migration |
| `tools/deckparts.py` | Helpers shared by the scripts above |

## Keeping content accurate

The slides describe the `idaholab/prometheus_core` monorepo (branch `devel`), with
`platform/`, `sdk/` (formerly `prometheus_api`) and `agent-template/` (formerly
`prometheus_agent_template`). When it changes, re-check the affected slides against
the code, not the repo's docs, which sometimes lag behind.
