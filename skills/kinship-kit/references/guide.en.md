# kinship-kit — English guide

The skill's main instructions (SKILL.md) are in Russian; this is the English version of the method and commands.
Always reply in the user's language; write search queries in the language of the source.

## Tool

All case work goes through the CLI of this skill (Python 3.10+, standard library only):
`python3 <skill folder>/kin.py <command>` — below simply `kin`. Interface language: `--lang en`, `KIN_LANG=en`
or the case language (`kin init … --lang en`). Labels and summaries are translated; case data stays as written.

A **case** is a private folder outside the skill and outside any public repository (e.g. `~/kinship-cases/<surname>`).

## First run

If the user has no case yet, ask in one message: the main surname (search line); the case title and folder;
the **commit author** for the case's git history — a name and e-mail or a pseudonym (never take it silently from the
global git settings: the history is visible to anyone who gets a copy); for which clients to install agent roles.
Then: `kin setup --yes --surname "…" --title "…" --author-name "…" --author-email "…" --agents both --lang en`
(or `--anonymous-author`). A person in a terminal can just run `kin setup` — it asks the same questions.

## Every session

1. `kin status` — active hypotheses, tasks, blocked items, negative searches, reviews, archive requests, family reports.
2. `kin next` — the ranked next actions with reasons; unavailable ones (paid without consent, attempt limit) separately.
3. `kin audit` — 0 errors before conclusions or publishing.

## Commands

| Task | Command |
|---|---|
| Register a document | `kin source add <file> --title … --kind document-image --repository … --ref "f. …, op. …, d. …, l. …" --group <independence group> --provenance "…"` |
| A person as written in a source | `kin mention add --artifact A-… --name "…as written…" --role child [--person P-… --link-status probable --rationale …]` |
| A person (research identity) | `kin person add --label "Surname Given Patronymic" --living deceased --status candidate` |
| A claim | `kin claim add --type birth --subject P-… --statement "…" --date 1885-03-02 --sources A-… --status single-source` |
| A relationship (stated in a source) | `kin rel add P-A parent-of P-B --claims C-… --status single-source` |
| Hypothesis, place | `kin add hypotheses|places --set field=value …` |
| Task from a template | `kin task new metric-books|archive-catalog|online-database|library|archive-request|archive-download|family-interview|tree-review --goal "…" [--hypothesis H-…]` |
| Task progress | `kin task start|block|review|done|close T-… [--reason …] [--evidence A-…]`; consent only by a person: `kin task consent T-… --granted --by "Name"` |
| Search log (also empty results) | `kin search add --task T-… --source … --query … --period 1880/1890 --result not-found --disallowed … --repeat-when …` |
| Hypothesis decision | `kin hypothesis status H-… supported|weakened|parked|rejected|accepted --reason "…" [--reopen "…"]` |
| Independent review | `kin review request <ID> --for accepted|rejected|strongly-corroborated|merge` → another role: `kin review checklist`, `kin review submit V-… --verdict … --checked A-… --findings …` → if needed a person: `kin review decide V-… --by "Name"` |
| Archive requests | `kin request add …`, `kin request sent Q-… --date … --number …`, `kin request answer Q-… --artifacts A-…` |
| Search the case | `kin find <words>` (any grammatical case, ё/е-insensitive) |
| Scans from an online archive | `kin downloader list` → `kin downloader build <adapter> --out f.js` (a script the user pastes into the browser console + instructions) → `kin source import-download <folder>`; a new site — write an adapter per `references/downloaders.md` |
| Site | `kin site build [--profile public]`, `kin site serve`, `kin site publish --to <folder>` (only with the user's consent) |
| Family reports | `kin case set feedback.enabled=true`, `kin feedback serve`, `kin feedback list|show|accept|reject` |
| Exchange | `kin export --out f.json`, `kin import f.json`, `kin gedcom export|import`, `kin backup`, `kin restore` |
| Agent roles | `kin agents install` (Claude Code `.claude/agents`, Codex `.codex/agents`) |
| MCP for clients without a shell | `kin mcp config --client claude-code|claude-desktop|codex` |

Sign changes with the role: `--as "Archive Researcher"` (or `KIN_ACTOR`). Never edit the CSV registers by hand.

## Non-negotiable rules

1. New material is an **artifact, not a fact**: `kin source add` first, then a claim with an assessment.
2. Copies, indexes, mirrors and retellings of one record are **one independence group**.
3. `corroborated` requires **two independent groups** and a rationale (`kin audit` treats it as an error otherwise).
   A family tree or family story (`family-tree`, `family-oral`) is a separate group **only** for facts about living people and
   one generation from them (themselves, their parents and children) — what the family knows first-hand. For more distant
   ancestors family information is a lead for the search, not a second confirmation (`kin audit` warns).
4. A document is not a person: a record in a source is a `mention`; linking it to a `person` is a separate, justified decision.
   Do not merge namesakes by name, age or village: two persons + an `identity` claim with status `hypothesis`.
5. A relationship only if the kinship is **stated in a source**; a shared patronymic or village is a hypothesis.
6. Different dates in different documents are **two claims** linked by `competing_claim_ids`; keep both.
7. Keep original spellings (`mention`, `name_variants`); the normalised form goes to `preferred_label`.
8. Absence of a result is not proof of absence: log every empty search with what may and may not be concluded and when to repeat.
   A repeated empty search is refused without `--new-basis`.
9. Do not close a hypothesis after one task; `rejected` needs contradicting sources and reopen conditions.
10. Do not invent missing facts; family memory stays `family-reported` until documents confirm it.
11. Close competing versions in the same commit as the finding. Before committing, run `kin find <person ID>`: a claim refuted by a source becomes
    `contradicted` or `rejected` (source in `contradicting_artifact_ids`, “Revised <date>: …” in `rationale`); a confirmed one is raised; a candidate who
    proved to be someone else becomes `unlikely`; a confirmed identity goes to `kin person merge`. Absence of a record alone does not refute a version:
    weaken it instead. Decisions that need review still go through review. Report the line “Hypotheses closed: N”.

## Independent review

Significant decisions (accept/reject a hypothesis, `strongly-corroborated`, merging people) need a passed review **of that
decision** by a different role, based on the primary sources, after the latest change of the record and its linked claims and
sources. Living or possibly living people require a human decision. Details: `docs/REVIEW.md` of the kit repository.

## Privacy

Distinguish (1) processing by the AI model the user chose; (2) sending data to third-party sites and archives — minimum
personal data, never search for living people; (3) publishing — only `kin site build --profile public`: living and
possibly living people are hidden, internal fields are dropped, the build fails on a leaked name, e-mail, phone or local path.
When in doubt, exclude (`kin update P-… publication=deny`). Paid actions and third-party services need the user's consent.
