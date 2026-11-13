# ME Atlas

*Mapping the evidence on ME/CFS and long COVID.*

ME Atlas gives patients, carers and researchers one continuously updated, evidence-graded overview of every serious hypothesis about what causes ME/CFS and long COVID. AI does most of the collecting and sorting; AI drafts, checks and audits, and no medical or research expert has reviewed the content yet; the founder sets the direction. It gives no treatment advice.

See [docs/ME-Atlas-v1-plan.md](docs/ME-Atlas-v1-plan.md) for the plan and [docs/pm/STATUS.md](docs/pm/STATUS.md) for where things stand.

## Development

```bash
cp .env.example .env   # fill in keys
uv sync
git config core.hooksPath .githooks   # blocks direct pushes to main
uv run pytest
```
