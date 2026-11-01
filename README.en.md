# kinship-kit — AI-assisted family history research

An evidence-first genealogy toolkit for AI agents (Claude Code, Codex): a **skill** (method) + the **`kin` CLI**
(all case operations) + a **family-tree site** (local or published). Family data lives in a separate private case folder.
Focus: former USSR and the Russian Empire. The method and most documentation are in Russian (English is planned, stage 3);
the agent replies in the user's language, and the site has an EN switch.

```bash
sh install.sh                                   # skill → ~/.claude/skills and ~/.agents/skills, plus `kin`
kin init ~/kinship-cases/smith --title "Smith" --lang en
kin status && kin audit && kin site serve       # http://127.0.0.1:8080
python3 examples/demo/build_demo.py /tmp/demo   # fictional demo case
```

Key ideas: sources are immutable and checksummed; a mention in a document is distinct from an established person;
corroboration requires two independent source groups; conflicting dates are kept as competing claims; negative searches
are logged with what may and may not be concluded; research state is restored from data (`kin status`); the public build
hides living people and fails on leaks. Architecture: `docs/ARCHITECTURE.md`.

License: MIT. Based on [ex-ussr-kinship-research](https://github.com/DenisSergeevitch/ex-ussr-kinship-research) © 2026 Denis Shiryaev (MIT).
