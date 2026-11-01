#!/usr/bin/env python3
"""Builds the English synthetic demo case with kin commands (fictional Vetlugin family).

python3 examples/demo/build_demo_en.py <case-folder>   # the folder must not exist and must be OUTSIDE the kit repository

Same acceptance scenarios as the Russian demo (build_demo.py): ambiguous identity, conflicting dates, negative search,
weak hypothesis sent to independent review, living relatives hidden from the public build, state recovery.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIN = HERE.parent.parent / "skills" / "kinship-kit" / "kin.py"
DOCS = HERE / "documents_en"


def kin(case: Path, *args: str, actor: str = "demo-builder") -> str:
    cmd = [sys.executable, str(KIN), "--lang", "en", *args]
    if args[0] != "init":
        cmd += ["--case", str(case), "--as", actor]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        sys.exit(f"Error: kin {' '.join(args)}\n{res.stderr}")
    return res.stdout.strip()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    case = Path(sys.argv[1]).expanduser().resolve()
    if case.exists():
        sys.exit(f"{case} already exists")
    print(kin(case, "init", str(case), "--title", "Vetlugin family (demo, fictional)", "--lang", "en"))

    def src(f, *a):
        return kin(case, "source", "add", str(DOCS / f), *a)

    img = ("--kind", "document-image", "--originality", "image-of-original", "--directness", "direct",
           "--repository", "GAOO (fictional)", "--provenance", "Image from the archive's online reading room (fictional)")
    src("birth-1885-no12.txt", "--title", "Holy Trinity register 1885, births No. 12", *img,
        "--ref", "f. 15, op. 2, d. 41, l. 7v", "--date", "1885-03-03", "--group", "reg-1885-12")              # A-0001
    src("index-1885.txt", "--title", "Index 'Olkhov registers', record 55102", "--kind", "index-record",
        "--url", "https://example.org/olkhov-registers/55102", "--originality", "index", "--directness", "direct",
        "--group", "reg-1885-12", "--provenance", "Index of the same register entry — not independent")       # A-0002
    src("marriage-1910-no4.txt", "--title", "Holy Trinity register 1910, marriages No. 4", *img,
        "--ref", "f. 15, op. 2, d. 66, l. 31", "--date", "1910-01-14", "--group", "reg-1910-m4")              # A-0003
    src("notice-1941.txt", "--title", "Death notice (family archive)", "--kind", "document-image", "--date", "1941",
        "--originality", "original", "--directness", "direct", "--group", "notice-1941",
        "--provenance", "Family archive, photocopy from the researcher")                                    # A-0004
    src("memorial-book-1942.txt", "--title", "Memorial Book of the Olkhov region, vol. 3, p. 212", "--kind", "book",
        "--date", "1995", "--originality", "derivative", "--directness", "direct", "--group", "mb-1942",
        "--provenance", "Published book; its primary loss report was not found")                          # A-0005
    src("civil-1921-no58.txt", "--title", "Civil registry extract, birth 1921 No. 58", "--kind", "official-extract",
        "--originality", "official-extract", "--directness", "direct", "--repository", "GAOO (fictional)",
        "--ref", "f. R-210, op. 1, d. 12, l. 40", "--date", "1921-07-15", "--group", "civil-1921-58",
        "--provenance", "Archive extract on request (fictional)")                                          # A-0006
    src("birth-1880-no31.txt", "--title", "Holy Trinity register 1880, births No. 31", *img,
        "--ref", "f. 15, op. 2, d. 36, l. 12", "--date", "1880-05-10", "--group", "reg-1880-31")              # A-0007
    src("draft-1903-no211.txt", "--title", "Zarechny district draft list 1903, No. 211", *img,
        "--ref", "f. 98, op. 1, d. 402, l. 55", "--date", "1903", "--group", "draft-1903")                    # A-0008
    src("family-story.txt", "--title", "Family story about Fyodor Somov", "--kind", "family-oral",
        "--originality", "family-information", "--group", "family-oral-1", "--provenance", "From the researcher")  # A-0009
    src("census-1858.txt", "--title", "Revision list 1858, Klenovka, household 14", "--kind", "document-image",
        "--originality", "image-of-original", "--directness", "indirect", "--repository", "GAOO (fictional)",
        "--ref", "f. 7, op. 1, d. 220, l. 18", "--date", "1858", "--group", "rev-1858",
        "--provenance", "Image from the archive's online reading room (fictional)")                         # A-0010
    src("birth-cert-1952.txt", "--title", "Birth certificate 1952 (living person)", "--kind", "document-image",
        "--originality", "original", "--group", "cert-1952", "--provenance", "The researcher's own document")   # A-0011
    src("researcher-form.txt", "--title", "Researcher's form", "--kind", "letter", "--originality", "family-information",
        "--group", "form", "--provenance", "Filled in by the researcher")                                  # A-0012

    def person(*a):
        return kin(case, "person", "add", *a)

    person("--label", "Vetlugin Ivan Kuzmich", "--sex", "m", "--living", "deceased", "--birth", "1855~",
           "--status", "identity-probable", "--line", "vetlugin", "--places", "Klenovka")                     # P-0001
    person("--label", "Vetlugin Pyotr Ivanovich", "--sex", "m", "--living", "deceased", "--birth", "1885-03-02",
           "--death", "1941/1942", "--status", "identity-confirmed", "--line", "vetlugin",
           "--variants", "Pyotr Ivanov Vetlugin", "--places", "Klenovka")                                     # P-0002
    person("--label", "Vetlugina (Somova) Maria Fyodorovna", "--sex", "f", "--living", "deceased", "--birth", "1889/1890",
           "--status", "identity-confirmed", "--line", "somov", "--variants", "Maria Fyodorova; Somova Maria Fyodorovna")  # P-0003
    person("--label", "Vetlugin Sergei Petrovich", "--sex", "m", "--living", "deceased", "--birth", "1921-07-10",
           "--death", "1999", "--status", "identity-confirmed", "--line", "vetlugin")                          # P-0004
    person("--label", "Vetlugina Anna Sergeevna", "--sex", "f", "--living", "living", "--birth", "1952",
           "--status", "identity-confirmed", "--line", "vetlugin", "--notes", "The researcher")               # P-0005
    person("--label", "Kornev Dmitry Andreevich", "--sex", "m", "--living", "living", "--birth", "1980",
           "--status", "family-reported")                                                                      # P-0006
    person("--label", "Vetlugin Ivan Petrovich (1880)", "--sex", "m", "--living", "deceased", "--birth", "1880-05-09",
           "--status", "candidate", "--line", "vetlugin", "--variants", "Ioann Petrov Vetlugin")              # P-0007
    person("--label", "Vetlugin Ivan Petrovich (draft 1903)", "--sex", "m", "--living", "unknown", "--birth", "1882~",
           "--status", "candidate", "--line", "vetlugin", "--variants", "Vetlugin Ivan Petrov")               # P-0008
    person("--label", "Vetlugin Kuzma", "--sex", "m", "--living", "deceased", "--birth", "../1835",
           "--status", "hypothesis", "--line", "vetlugin")                                                     # P-0009
    person("--label", "Somov Fyodor", "--sex", "m", "--living", "deceased", "--status", "family-reported",
           "--line", "somov", "--death", "../1917")                                                            # P-0010

    def mention(*a):
        return kin(case, "mention", "add", *a)

    mention("--artifact", "A-0001", "--name", "Pyotr", "--role", "child", "--date", "2 March 1885", "--person", "P-0002",
            "--link-status", "confirmed", "--rationale", "Date and parents match the 1921 extract and the 1910 marriage")
    mention("--artifact", "A-0001", "--name", "Ivan Kuzmin Vetlugin", "--role", "father", "--person", "P-0001",
            "--link-status", "probable", "--rationale", "Patronymic and village; the only Ivan Kuzmin in the 1858 list")
    mention("--artifact", "A-0007", "--name", "Ioann", "--role", "child", "--date", "9 May 1880", "--person", "P-0007",
            "--link-status", "confirmed", "--rationale", "The record the candidate is based on")
    mention("--artifact", "A-0008", "--name", "Vetlugin Ivan Petrov", "--role", "soldier", "--age", "21",
            "--person", "P-0008", "--link-status", "confirmed", "--rationale", "The record the candidate is based on")
    mention("--artifact", "A-0010", "--name", "Ivan Kuzmin", "--role", "household-member", "--age", "3",
            "--person", "P-0001", "--link-status", "probable", "--rationale", "Age ≈1855, Klenovka")

    def claim(*a):
        return kin(case, "claim", "add", *a)

    claim("--type", "birth", "--subject", "P-0002", "--statement", "Pyotr Ivanovich was born on 2 March 1885 in Klenovka",
          "--date", "1885-03-02", "--place", "Klenovka", "--sources", "A-0001;A-0002", "--mentions", "M-0001",
          "--status", "single-source", "--confidence", "high",
          "--rationale", "The register and its index are one group (reg-1885-12): not corroboration")       # C-0001
    claim("--type", "death", "--subject", "P-0002", "--statement", "Pyotr Ivanovich was killed on 18 November 1941",
          "--date", "1941-11-18", "--sources", "A-0004", "--status", "contradicted", "--against", "A-0005",
          "--rationale", "Notice versus the Memorial Book; both versions kept")                               # C-0002
    claim("--type", "death", "--subject", "P-0002", "--statement", "Pyotr Ivanovich died of wounds in February 1942",
          "--date", "1942-02", "--sources", "A-0005", "--status", "contradicted", "--against", "A-0004",
          "--competing", "C-0002", "--rationale", "The Memorial Book is derivative; the primary report was not found")  # C-0003
    claim("--type", "marriage", "--subject", "P-0002;P-0003", "--statement", "Marriage of Pyotr Ivanov Vetlugin and Maria Fyodorova Somova",
          "--date", "1910-01-14", "--place", "Klenovka, Holy Trinity church", "--sources", "A-0003", "--status", "single-source")  # C-0004
    claim("--type", "birth", "--subject", "P-0004", "--statement", "Sergei Petrovich was born on 10 July 1921",
          "--date", "1921-07-10", "--sources", "A-0006", "--status", "single-source")                         # C-0005
    claim("--type", "parentage", "--subject", "P-0002;P-0004", "--statement", "Pyotr Ivanovich is the father of Sergei Petrovich",
          "--sources", "A-0006", "--status", "single-source")                                                 # C-0006
    claim("--type", "parentage", "--subject", "P-0001;P-0002", "--statement", "Ivan Kuzmich is Pyotr's father (1885 register)",
          "--sources", "A-0001", "--status", "single-source")                                                 # C-0007
    claim("--type", "identity", "--subject", "P-0007;P-0008", "--statement",
          "Possibly the same person: Ioann b. 1880 and Ivan Petrov, 21 in 1903", "--sources", "A-0007;A-0008",
          "--status", "hypothesis", "--rationale", "The draft age gives ≈1882, not 1880; there may have been two Ivan Petrovichs")  # C-0008
    claim("--type", "parentage", "--subject", "P-0009;P-0001", "--statement", "Kuzma Vetlugin is the father of Ivan Kuzmich",
          "--status", "hypothesis", "--rationale", "Inferred only from the patronymic 'Kuzmin'")              # C-0009
    claim("--type", "parentage", "--subject", "P-0010;P-0003", "--statement", "Fyodor Somov is the father of Maria Fyodorovna",
          "--sources", "A-0003;A-0009", "--status", "corroborated",
          "--rationale", "1910 marriage record ('daughter of Fyodor Somov') and an independent family story")  # C-0010
    claim("--type", "birth", "--subject", "P-0001", "--statement", "Ivan Kuzmich was born about 1855",
          "--date", "1855~", "--sources", "A-0010", "--mentions", "M-0005", "--status", "single-source",
          "--rationale", "Aged 3 in the 1858 revision list")                                                  # C-0011
    claim("--type", "parentage", "--subject", "P-0004;P-0005", "--statement", "Sergei Petrovich is the father of Anna Sergeevna",
          "--sources", "A-0011", "--status", "single-source")                                                 # C-0012

    def rel(*a):
        return kin(case, "rel", "add", *a)

    rel("P-0001", "parent-of", "P-0002", "--claims", "C-0007", "--status", "single-source", "--nature", "biological")
    rel("P-0002", "spouse-of", "P-0003", "--claims", "C-0004", "--status", "single-source")
    rel("P-0002", "parent-of", "P-0004", "--claims", "C-0006", "--status", "single-source", "--nature", "biological")
    rel("P-0003", "parent-of", "P-0004", "--sources", "A-0006", "--status", "single-source", "--nature", "biological")
    rel("P-0010", "parent-of", "P-0003", "--claims", "C-0010", "--status", "corroborated",
        "--rationale", "Two independent groups: marriage record and family story")
    rel("P-0004", "parent-of", "P-0005", "--claims", "C-0012", "--status", "single-source")
    rel("P-0005", "parent-of", "P-0006", "--sources", "A-0012", "--status", "single-source")

    def add(reg, *a):
        return kin(case, "add", reg, *a)

    add("hypotheses", "--set", "statement=Ivan Kuzmich's father was Kuzma Vetlugin of Klenovka",
        "--set", "person_ids=P-0001;P-0009", "--set", "claim_ids=C-0009",
        "--set", "alternatives='Kuzmin' may be a household nickname or a stepfather's name; Kuzma may come from another village",
        "--set", "test_plan=Find Ivan's birth ≈1854–1856 (registers, consistory copies), the 1850 revision list",
        "--set", "status=open", "--set", "owner=Genealogy Researcher")                                       # H-0001
    add("hypotheses", "--set", "statement=Candidates P-0007 and P-0008 are the same person",
        "--set", "person_ids=P-0007;P-0008", "--set", "claim_ids=C-0008", "--set", "supporting_artifact_ids=A-0007;A-0008",
        "--set", "alternatives=Two different Ivan Petrovichs in one village",
        "--set", "open_contradictions=The draft list age (21 in 1903) points to 1882, not 1880",
        "--set", "test_plan=Confession lists 1897–1903; household list 1903",
        "--set", "status=testing", "--set", "owner=Genealogy Researcher")                                    # H-0002

    kin(case, "task", "new", "metric-books", "--hypothesis", "H-0002", "--priority", "1", "--value", "4", "--cost", "free",
        "--access", "online", "--goal", "Check confession lists 1897–1903: how many Ivan Petrovichs lived in Klenovka",
        "--expected", "Households with an Ivan Petrovich and their ages",
        "--sources", "GAOO f. 15 op. 3 (confession lists, fictional)")                                       # T-0001
    kin(case, "task", "new", "archive-request", "--hypothesis", "H-0001", "--priority", "2", "--value", "5", "--cost", "paid",
        "--goal", "Request consistory copies of the 1854–1856 registers", "--sources", "GAOO f. 20 (consistory, fictional)")  # T-0002
    kin(case, "task", "new", "metric-books", "--hypothesis", "H-0001", "--priority", "2", "--value", "5", "--cost", "free",
        "--goal", "Search Ivan's birth in the Holy Trinity registers 1853–1857")                             # T-0003
    kin(case, "task", "start", "T-0003")
    kin(case, "search", "add", "--task", "T-0003", "--date", "2026-10-20", "--persons", "P-0001",
        "--source", "GAOO (fictional), f. 15, op. 2 — Holy Trinity registers",
        "--query", "Birth of Ivan, son of Kuzma, 1853–1857", "--variants", "Ivan/Ioann; Kuzmin/Kozmin; Vetlugin/Vetlyugin",
        "--period", "1853/1857", "--limits", "Books for 1854–1856 are listed as lost",
        "--result", "not-found", "--allowed", "No such record in the surviving 1853 and 1857 books",
        "--disallowed", "We cannot conclude Ivan was born elsewhere or that his father was not Kuzma",
        "--repeat-when", "Consistory copies (f. 20) for 1854–1856 are found", "--next", "Request the consistory copies")  # S-0001
    kin(case, "task", "close", "T-0003", "--reason",
        "Books for 1854–1856 are lost; no record in 1853 and 1857. H-0001 is not refuted", "--next", "T-0002")
    kin(case, "search", "add", "--date", "2026-10-21", "--persons", "P-0002",
        "--source", "Memorial Book of the Olkhov region (fictional)", "--query", "Vetlugin Pyotr Ivanovich",
        "--period", "1941/1945", "--result", "found", "--artifacts", "A-0005",
        "--allowed", "There is a February 1942 version of the death", "--disallowed", "1942 does not cancel the 1941 notice")  # S-0002
    (case / "requests" / "Q-0001.md").write_text(
        "Request (fictional, demo): please tell us whether consistory copies of the Holy Trinity (Klenovka) registers for\n"
        "1854–1856 survive and provide a copy of the birth record of Ivan, son of Kuzma Vetlugin.\n", encoding="utf-8")
    kin(case, "request", "add", "--task", "T-0002", "--recipient", "GAOO (fictional)",
        "--subject", "Consistory copies of the Holy Trinity registers 1854–1856", "--channel", "gov-portal",
        "--text", "requests/Q-0001.md", "--cost", "per the archive's invoice")                               # Q-0001
    # scenario 5: a weak hypothesis (patronymic only) goes to independent review — and fails
    kin(case, "review", "request", "H-0001", "--for", "accepted")                                            # V-0001
    kin(case, "review", "submit", "V-0001", "--verdict", "needs-work", "--findings",
        "Paternity is inferred only from the patronymic 'Kuzmin'; no supporting sources; alternatives (stepfather, "
        "another Kuzma) are not excluded. A birth record or the 1850 revision list naming the father is needed.",
        actor="Evidence Reviewer")
    add("places", "--set", "name=Klenovka", "--set", "kind=village", "--set", "name_variants=Klyonovka; Klenovaya",
        "--set", "jurisdictions=until 1924: Olkhov province, Zarechny district, Klenovka volost; 1924–1929: Zarechny volost; "
                 "from 1929: Zarechny raion (all fictional)")
    kin(case, "case", "set", "root_person=P-0005")
    kin(case, "case", "line", "add", "vetlugin", "title=Vetlugin", "surname=Vetlugin", "state=searching now",
        "where=GAOO f. 15 — Holy Trinity registers", "color=#b5651d")
    kin(case, "case", "line", "add", "somov", "title=Somov", "surname=Somov", "state=awaiting a reply",
        "where=Sosnovka", "color=#2f6b8a")
    print(f"Demo case ready: {case}\nNext: kin --case {case} next")


if __name__ == "__main__":
    main()
