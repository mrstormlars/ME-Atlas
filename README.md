# ME Atlas

*Mapping the evidence on ME/CFS and long COVID.*

> **What this is, before anything else.** The content of ME Atlas is drafted, checked and graded by AI: one AI agent drafts, a second AI agent checks, and an independent AI auditor decides the evidence levels. No medical or research expert has reviewed it. It gives no treatment advice. The founder sets the direction (the rubric, the inclusion rule, the scope) and may overrule the auditor, as a logged correction.

ME Atlas aims to contribute to solving ME/CFS. It collects and grades what is known about the causes of ME/CFS and long COVID, shows how the hypotheses connect, and makes visible what has not been tested, so that researchers can see where the next study would matter and patients and carers can follow the state of the evidence.

It is for researchers, and for patients and carers, as readers of equal weight. Each hypothesis has a card: what it claims, the studies that bear on it (with sample size and case definition beside each), what contradicts it, and how far along the evidence ladder it is. The site shows no ranking of "most promising" ideas and never says a hypothesis is right or wrong.

The site is at <https://mrstormlars.github.io/ME-Atlas/> (Norwegian: `nb/`). It is rebuilt from the approved cards on every change to `main`.

## How grading works

Every hypothesis is graded on a published evidence ladder, level 0 (proposed) to level 5 (causal case built), with the case definition of each study recorded (Fukuda, CCC, ICC, IOM 2015, Oxford and so on; an Oxford-only cohort is flagged as broad). Nothing is graded by criteria that are not in the ladder. Contested evidence is marked as contested.

- The ladder, the inclusion rule and the editorial flow: [docs/ME-Atlas-functional-spec.md](docs/ME-Atlas-functional-spec.md) (sections 2, 3 and 6).
- The same in plain language, as shown on the site: [content/methods/en.html](content/methods/en.html).
- How the weekly pipeline works: [docs/pipeline.md](docs/pipeline.md).

A weekly pipeline fetches new papers from PubMed and Europe PMC. Code checks every citation mechanically (the identifier exists, and title, year and case definition match the fetched record; a sample size that does not match is a warning, not a failure). A change that moves a level, badge, contested mark, layer, link or preprint signal reaches a card only when the checks pass, the review agent accepts it and the independent auditor accepts it. A dispute leaves the card unchanged. The one exception is a finding that the reviewer or auditor classes as wording only, in a correction round or a link round: the named sentence is reworded or removed and the review agent checks it once (see [the methods text](content/methods/en.html)). The auditor shares a model family with the agents it audits and may share their blind spots; the methods text says so.

## Report an error or suggest a paper

Use the issue forms on GitHub (Issues, then New issue):

- **Report an error on a card:** name the card, quote the sentence, give the source that shows it is wrong, and say what it should say.
- **Suggest a paper:** give a PMID or DOI and the hypothesis it bears on.
- **Suggest a hypothesis** or report a **bug or site problem**.

Questions and general discussion go to Discussions, not to issues. English and Norwegian are both welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for what a good report contains and for how code contributions work, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) for the rules of conduct. Security problems: see [SECURITY.md](SECURITY.md).

Evidence content (`cards/`, `drafts/`, `translations/`, `audits/`) is never changed by an outside pull request: it enters only through the pipeline. A suggestion for the content is an issue.

## Run it

Needs Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env   # NCBI_API_KEY is optional; CONTACT_EMAIL is sent to NCBI and Europe PMC
uv sync
git config core.hooksPath .githooks   # blocks direct pushes to main
uv run pytest
uv run python -m me_atlas.site build   # writes the static site to build/
```

The tests are offline: they never touch the network or an AI model. The AI steps run as Claude Code subagents defined in `.claude/agents/`; see [CLAUDE.md](CLAUDE.md) and [docs/pipeline.md](docs/pipeline.md).

For the plan and where things stand: [docs/ME-Atlas-v1-plan.md](docs/ME-Atlas-v1-plan.md) and [docs/pm/STATUS.md](docs/pm/STATUS.md).

## Licences

- Code, tests and build files: MIT, see [LICENSE](LICENSE).
- Evidence content, documentation, site text and the generated site: CC BY 4.0, see [LICENSE-CONTENT](LICENSE-CONTENT).
- Article titles and sentences quoted from papers stay with their rights holders and are not relicensed. Raw API responses and full texts are not in this repository and must stay out of it.
