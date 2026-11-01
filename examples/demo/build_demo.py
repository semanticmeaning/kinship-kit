#!/usr/bin/env python3
"""Строит синтетическое демо-дело командами kin (вымышленная семья Ветлугиных).

python3 examples/demo/build_demo.py <папка-дела>     # папка должна не существовать и лежать ВНЕ репозитория набора

Покрывает сценарии приёмки: неоднозначная личность, противоречие дат, отрицательный поиск,
слабая гипотеза для ревью, живые родственники (не попадают в публичную сборку), восстановление состояния.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIN = HERE.parent.parent / "skills" / "kinship-kit" / "kin.py"
DOCS = HERE / "documents"


def kin(case: Path, *args: str) -> str:
    cmd = [sys.executable, str(KIN), *args]
    if args[0] != "init":
        cmd += ["--case", str(case), "--as", "demo-builder"]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        sys.exit(f"Ошибка: kin {' '.join(args)}\n{res.stderr}")
    return res.stdout.strip()


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    case = Path(sys.argv[1]).expanduser().resolve()
    if case.exists():
        sys.exit(f"{case} уже существует")
    print(kin(case, "init", str(case), "--title", "Ветлугины (демо, вымышленная семья)"))

    src = lambda f, *a: kin(case, "source", "add", str(DOCS / f), *a)  # noqa: E731
    # A-0001..A-0012 — порядок важен для ссылок ниже
    src("metrika-1885-rozhd-12.txt", "--title", "МК Троицкой ц. с. Кленовки 1885, рожд. № 12", "--kind", "document-image",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. 15, оп. 2, д. 41, л. 7 об.", "--date", "1885-03-03",
        "--directness", "direct", "--originality", "image-of-original", "--group", "mk-1885-12",
        "--provenance", "Образ из электронного читального зала архива (вымышл.)")
    src("index-site-1885.txt", "--title", "Индекс «Олховские метрики», запись 55102", "--kind", "index-record",
        "--url", "https://example.org/olhov-metriki/55102", "--directness", "direct", "--originality", "index",
        "--group", "mk-1885-12", "--provenance", "Индекс той же метрической записи — не независим")
    src("metrika-1910-brak-4.txt", "--title", "МК Троицкой ц. 1910, браки № 4", "--kind", "document-image",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. 15, оп. 2, д. 66, л. 31", "--date", "1910-01-14",
        "--directness", "direct", "--originality", "image-of-original", "--group", "mk-1910-b4",
        "--provenance", "Образ из электронного читального зала (вымышл.)")
    src("izveshchenie-1941.txt", "--title", "Извещение о гибели (семейный архив)", "--kind", "document-image",
        "--date", "1941", "--directness", "direct", "--originality", "original", "--group", "izv-1941",
        "--provenance", "Семейный архив, фотокопия от автора исследования")
    src("kniga-pamyati-1942.txt", "--title", "Книга памяти Ольховской обл., т. 3, с. 212", "--kind", "book",
        "--date", "1995", "--directness", "direct", "--originality", "derivative", "--group", "kp-1942",
        "--provenance", "Опубликованная книга; первоисточник — донесение о потерях (не найдено)")
    src("svid-1921.txt", "--title", "Выписка ЗАГС о рождении 1921, № 58", "--kind", "official-extract",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. Р-210, оп. 1, д. 12, л. 40", "--date", "1921-07-15",
        "--directness", "direct", "--originality", "official-extract", "--group", "zags-1921-58",
        "--provenance", "Архивная выписка по запросу (вымышл.)")
    src("metrika-1880-rozhd-31.txt", "--title", "МК Троицкой ц. 1880, рожд. № 31", "--kind", "document-image",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. 15, оп. 2, д. 36, л. 12", "--date", "1880-05-10",
        "--directness", "direct", "--originality", "image-of-original", "--group", "mk-1880-31",
        "--provenance", "Образ из электронного читального зала (вымышл.)")
    src("prizyv-1903.txt", "--title", "Призывной список Заречного у. 1903, № 211", "--kind", "document-image",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. 98, оп. 1, д. 402, л. 55", "--date", "1903",
        "--directness", "direct", "--originality", "image-of-original", "--group", "prizyv-1903",
        "--provenance", "Образ из электронного читального зала (вымышл.)")
    src("rasskaz-semyi.txt", "--title", "Рассказ семьи о Фёдоре Сомове", "--kind", "family-oral",
        "--originality", "family-information", "--group", "family-oral-1", "--provenance", "Со слов автора исследования")
    src("revizskaya-1858.txt", "--title", "Ревизская сказка 1858, д. Кленовка, двор 14", "--kind", "document-image",
        "--repository", "ГАОО (вымышл.)", "--ref", "ф. 7, оп. 1, д. 220, л. 18", "--date", "1858",
        "--directness", "indirect", "--originality", "image-of-original", "--group", "rs-1858",
        "--provenance", "Образ из электронного читального зала (вымышл.)")
    src("svid-1952.txt", "--title", "Свидетельство о рождении 1952 (живой человек)", "--kind", "document-image",
        "--originality", "original", "--group", "svid-1952", "--provenance", "Личный документ автора")
    src("anketa-avtora.txt", "--title", "Анкета автора исследования", "--kind", "letter",
        "--originality", "family-information", "--group", "anketa", "--provenance", "Заполнена автором исследования")

    P = lambda *a: kin(case, "person", "add", *a)  # noqa: E731
    P("--label", "Ветлугин Иван Кузьмич", "--sex", "m", "--living", "deceased", "--birth", "1855~",
      "--status", "identity-probable", "--line", "vetluginy", "--places", "д. Кленовка")                       # P-0001
    P("--label", "Ветлугин Пётр Иванович", "--sex", "m", "--living", "deceased", "--birth", "1885-03-02",
      "--death", "1941/1942", "--status", "identity-confirmed", "--line", "vetluginy", "--variants", "Петр Иванов Ветлугин",
      "--places", "д. Кленовка")                                                                              # P-0002
    P("--label", "Ветлугина (Сомова) Мария Фёдоровна", "--sex", "f", "--living", "deceased", "--birth", "1889/1890",
      "--status", "identity-confirmed", "--line", "somovy", "--variants", "Мария Федорова; Сомова Мария Федоровна")  # P-0003
    P("--label", "Ветлугин Сергей Петрович", "--sex", "m", "--living", "deceased", "--birth", "1921-07-10",
      "--death", "1999", "--status", "identity-confirmed", "--line", "vetluginy")                                # P-0004
    P("--label", "Ветлугина Анна Сергеевна", "--sex", "f", "--living", "living", "--birth", "1952",
      "--status", "identity-confirmed", "--line", "vetluginy", "--notes", "Автор исследования")                  # P-0005
    P("--label", "Корнев Дмитрий Андреевич", "--sex", "m", "--living", "living", "--birth", "1980",
      "--status", "family-reported")                                                                            # P-0006
    P("--label", "Ветлугин Иван Петрович (1880)", "--sex", "m", "--living", "deceased", "--birth", "1880-05-09",
      "--status", "candidate", "--line", "vetluginy", "--variants", "Иоанн Петров Ветлугин")                    # P-0007
    P("--label", "Ветлугин Иван Петрович (призыв 1903)", "--sex", "m", "--living", "unknown", "--birth", "1882~",
      "--status", "candidate", "--line", "vetluginy", "--variants", "Ветлугин Иван Петров")                     # P-0008
    P("--label", "Ветлугин Кузьма", "--sex", "m", "--living", "deceased", "--birth", "../1835",
      "--status", "hypothesis", "--line", "vetluginy")                                                          # P-0009
    P("--label", "Сомов Фёдор", "--sex", "m", "--living", "deceased", "--status", "family-reported",
      "--line", "somovy", "--death", "../1917")                                                                 # P-0010

    M = lambda *a: kin(case, "mention", "add", *a)  # noqa: E731
    M("--artifact", "A-0001", "--name", "Петр", "--role", "child", "--date", "2 марта 1885", "--person", "P-0002",
      "--link-status", "confirmed", "--rationale", "Дата и родители совпадают с выпиской 1921 и браком 1910")    # M-0001
    M("--artifact", "A-0001", "--name", "Иван Кузьмин Ветлугин", "--role", "father", "--person", "P-0001",
      "--link-status", "probable", "--rationale", "Отчество и деревня; единственный Иван Кузьмин в РС 1858")     # M-0002
    M("--artifact", "A-0007", "--name", "Иоанн", "--role", "child", "--date", "9 мая 1880", "--person", "P-0007",
      "--link-status", "confirmed", "--rationale", "Запись о рождении — основание кандидата")                    # M-0003
    M("--artifact", "A-0008", "--name", "Ветлугин Иван Петров", "--role", "soldier", "--age", "21 год",
      "--person", "P-0008", "--link-status", "confirmed", "--rationale", "Запись — основание кандидата")         # M-0004
    M("--artifact", "A-0010", "--name", "Ивана Кузьмина", "--role", "household-member", "--age", "3 года",
      "--person", "P-0001", "--link-status", "probable", "--rationale", "Возраст ≈1855, Кленовка")              # M-0005

    C = lambda *a: kin(case, "claim", "add", *a)  # noqa: E731
    C("--type", "birth", "--subject", "P-0002", "--statement", "Пётр Иванович родился 2 марта 1885 г. в д. Кленовка",
      "--date", "1885-03-02", "--place", "д. Кленовка", "--sources", "A-0001;A-0002", "--mentions", "M-0001",
      "--status", "single-source", "--confidence", "high",
      "--rationale", "Метрика и её индекс — одна группа (mk-1885-12): не кроссподтверждение")                    # C-0001
    C("--type", "death", "--subject", "P-0002", "--statement", "Пётр Иванович погиб 18 ноября 1941 г.",
      "--date", "1941-11-18", "--sources", "A-0004", "--status", "contradicted", "--against", "A-0005",
      "--rationale", "Извещение против Книги памяти; обе версии сохранены")                                     # C-0002
    C("--type", "death", "--subject", "P-0002", "--statement", "Пётр Иванович умер от ран в феврале 1942 г.",
      "--date", "1942-02", "--sources", "A-0005", "--status", "contradicted", "--against", "A-0004",
      "--competing", "C-0002", "--rationale", "Книга памяти — производный источник; первичное донесение не найдено") # C-0003
    C("--type", "marriage", "--subject", "P-0002;P-0003", "--statement", "Брак Петра Иванова Ветлугина и Марии Федоровой Сомовой",
      "--date", "1910-01-14", "--place", "с. Кленовка, Троицкая ц.", "--sources", "A-0003", "--status", "single-source") # C-0004
    C("--type", "birth", "--subject", "P-0004", "--statement", "Сергей Петрович родился 10 июля 1921 г.",
      "--date", "1921-07-10", "--sources", "A-0006", "--status", "single-source")                               # C-0005
    C("--type", "parentage", "--subject", "P-0002;P-0004", "--statement", "Пётр Иванович — отец Сергея Петровича",
      "--sources", "A-0006", "--status", "single-source")                                                       # C-0006
    C("--type", "parentage", "--subject", "P-0001;P-0002", "--statement", "Иван Кузьмич — отец Петра (метрика 1885)",
      "--sources", "A-0001", "--status", "single-source")                                                       # C-0007
    C("--type", "identity", "--subject", "P-0007;P-0008", "--statement",
      "Возможно, одно лицо: Иоанн 1880 г. р. и Иван Петров, 21 год в 1903 г.", "--sources", "A-0007;A-0008",
      "--status", "hypothesis", "--rationale", "Возраст в списке даёт ≈1882, а не 1880; в деревне могло быть два Ивана Петровича") # C-0008
    C("--type", "parentage", "--subject", "P-0009;P-0001", "--statement", "Кузьма Ветлугин — отец Ивана Кузьмича",
      "--status", "hypothesis", "--rationale", "Выведено только из отчества «Кузьмин»")                          # C-0009
    C("--type", "parentage", "--subject", "P-0010;P-0003", "--statement", "Фёдор Сомов — отец Марии Фёдоровны",
      "--sources", "A-0003;A-0009", "--status", "corroborated",
      "--rationale", "Метрика брака 1910 («Федора Сомова дочь») и независимый рассказ семьи")                    # C-0010
    C("--type", "birth", "--subject", "P-0001", "--statement", "Иван Кузьмич родился около 1855 г.",
      "--date", "1855~", "--sources", "A-0010", "--mentions", "M-0005", "--status", "single-source",
      "--rationale", "Возраст 3 года в РС 1858")                                                                  # C-0011
    C("--type", "parentage", "--subject", "P-0004;P-0005", "--statement", "Сергей Петрович — отец Анны Сергеевны",
      "--sources", "A-0011", "--status", "single-source")                                                       # C-0012

    R = lambda *a: kin(case, "rel", "add", *a)  # noqa: E731
    R("P-0001", "parent-of", "P-0002", "--claims", "C-0007", "--status", "single-source", "--nature", "biological")
    R("P-0002", "spouse-of", "P-0003", "--claims", "C-0004", "--status", "single-source")
    R("P-0002", "parent-of", "P-0004", "--claims", "C-0006", "--status", "single-source", "--nature", "biological")
    R("P-0003", "parent-of", "P-0004", "--sources", "A-0006", "--status", "single-source", "--nature", "biological")
    R("P-0010", "parent-of", "P-0003", "--claims", "C-0010", "--status", "corroborated",
      "--rationale", "Две независимые группы: метрика брака и рассказ семьи")
    R("P-0004", "parent-of", "P-0005", "--claims", "C-0012", "--status", "single-source")
    R("P-0005", "parent-of", "P-0006", "--sources", "A-0012", "--status", "single-source")

    A = lambda reg, *a: kin(case, "add", reg, *a)  # noqa: E731
    A("hypotheses", "--set", "statement=Отец Ивана Кузьмича — Кузьма Ветлугин из д. Кленовка",
      "--set", "person_ids=P-0001;P-0009", "--set", "claim_ids=C-0009",
      "--set", "alternatives=«Кузьмин» — прозвище двора или отчество отчима; Кузьма мог быть из другой деревни",
      "--set", "test_plan=Найти рождение Ивана ≈1854–1856 (метрики, консисторские дубликаты), РС 1850",
      "--set", "status=open", "--set", "owner=Genealogy Researcher")                                           # H-0001
    A("hypotheses", "--set", "statement=Кандидаты P-0007 и P-0008 — одно лицо",
      "--set", "person_ids=P-0007;P-0008", "--set", "claim_ids=C-0008",
      "--set", "supporting_artifact_ids=A-0007;A-0008",
      "--set", "alternatives=Два разных Ивана Петровича в одной деревне",
      "--set", "open_contradictions=Возраст в призывном списке (21 год в 1903) указывает на 1882, а не 1880",
      "--set", "test_plan=Исповедные ведомости 1897–1903; посемейный список 1903",
      "--set", "status=testing", "--set", "owner=Genealogy Researcher")                                        # H-0002
    T = lambda *a: kin(case, "task", *a)  # noqa: E731
    T("new", "metric-books", "--hypothesis", "H-0002", "--priority", "1", "--value", "4", "--cost", "free",
      "--access", "online", "--goal", "Проверить исповедные ведомости 1897–1903: сколько Иванов Петровичей в Кленовке",
      "--expected", "Список дворов с Иванами Петровичами и их возрастами",
      "--sources", "ГАОО ф. 15 оп. 3 (исповедные ведомости, вымышл.)")                                          # T-0001
    T("new", "archive-request", "--hypothesis", "H-0001", "--priority", "2", "--value", "5", "--cost", "paid",
      "--goal", "Запросить консисторские дубликаты метрик 1854–1856",
      "--sources", "ГАОО ф. 20 (консистория, вымышл.)")                                                         # T-0002 — ждёт согласия
    T("new", "metric-books", "--hypothesis", "H-0001", "--priority", "2", "--value", "5", "--cost", "free",
      "--goal", "Поиск рождения Ивана в метриках Троицкой ц. 1853–1857")                                         # T-0003
    kin(case, "task", "start", "T-0003")
    kin(case, "search", "add", "--task", "T-0003", "--date", "2026-10-20", "--persons", "P-0001",
        "--source", "ГАОО (вымышл.), ф. 15, оп. 2 — метрики Троицкой ц.",
        "--query", "Рождение Ивана, сына Кузьмы, 1853–1857",
        "--variants", "Иван/Иоанн; Кузьмин/Козьмин; Ветлугин/Ветлюгин", "--period", "1853/1857",
        "--limits", "Книги 1854–1856 в описи значатся утраченными", "--result", "not-found",
        "--allowed", "В сохранившихся книгах 1853 и 1857 записи нет",
        "--disallowed", "Нельзя считать, что Иван родился не в Кленовке или что отец не Кузьма",
        "--repeat-when", "Найдены консисторские дубликаты (ф. 20) за 1854–1856",
        "--next", "Запрос о консисторских дубликатах")                                                          # S-0001
    kin(case, "task", "close", "T-0003", "--reason",
        "Книги 1854–1856 утрачены; в 1853 и 1857 записи нет. Гипотеза H-0001 не опровергнута", "--next", "T-0002")
    kin(case, "search", "add", "--date", "2026-10-21", "--persons", "P-0002",
        "--source", "Книга памяти Ольховской обл. (вымышл.)", "--query", "Ветлугин Петр Иванович",
        "--period", "1941/1945", "--result", "found", "--artifacts", "A-0005",
        "--allowed", "Есть версия смерти 02.1942", "--disallowed", "Дата 1942 не отменяет извещения 1941")       # S-0002
    (case / "requests" / "Q-0001.md").write_text(
        "Запрос (вымышленный, демо): прошу сообщить, сохранились ли консисторские экземпляры метрических книг\n"
        "Троицкой церкви с. Кленовки за 1854–1856 гг. и выдать копию записи о рождении Ивана, сына Кузьмы Ветлугина.\n",
        encoding="utf-8")
    kin(case, "request", "add", "--task", "T-0002", "--recipient", "ГАОО (вымышл.)",
        "--subject", "Консисторские дубликаты метрик Троицкой ц. 1854–1856", "--channel", "gov-portal",
        "--text", "requests/Q-0001.md", "--cost", "по счёту архива")                                             # Q-0001
    # сценарий 5: слабая гипотеза (только по отчеству) уходит на независимое ревью — и не проходит
    kin(case, "review", "request", "H-0001")                                                                    # V-0001
    subprocess.run([sys.executable, str(KIN), "review", "submit", "V-0001", "--verdict", "needs-work",
                    "--findings", "Отцовство выведено только из отчества «Кузьмин»; источников «за» нет; "
                                  "альтернативы (отчим, другой Кузьма) не исключены. Нужна метрика рождения или РС 1850 с именем отца.",
                    "--case", str(case), "--as", "Evidence Reviewer"], check=True, capture_output=True)
    A("places", "--set", "name=Кленовка", "--set", "kind=village", "--set", "name_variants=Клёновка; Кленовая",
      "--set", "jurisdictions=до 1924: Ольховская губ., Заречный у., Кленовская вол.; 1924–1929: Заречная вол.; с 1929: Заречный р-н (всё вымышлено)")

    kin(case, "case", "set", "root_person=P-0005")
    kin(case, "case", "line", "add", "vetluginy", "title=Ветлугины", "surname=Ветлугин", "state=ищем сейчас",
        "where=ГАОО ф. 15 — метрики Троицкой ц.", "color=#b5651d")
    kin(case, "case", "line", "add", "somovy", "title=Сомовы", "surname=Сомов", "state=ждём ответа",
        "where=д. Сосновка", "color=#2f6b8a")
    print(f"Демо-дело готово: {case}\nДальше: kin --case {case} status")


if __name__ == "__main__":
    main()
