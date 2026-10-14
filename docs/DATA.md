# Catalog data

Coverage reflects the checked-in snapshots collected on **October 13, 2026**.

| Dataset | Coverage |
| --- | --- |
| Current courses | 2026–2027: 6,034 courses across 162 subjects |
| Current undergraduate requirements | 2026–2027: 395 bachelor program variants, 22 concentration pages, and 2 shared requirement documents |
| Archived requirements | 2022–2023 through 2025–2026, including edition-specific concentrations and course descriptions |
| Active sample plans | Historical 2025–2026 plans; the checked 2026–2027 edition had no published sample-plan grids |
| AP/IB policies | 2026–2027 only; saved exams pin their policy version independently of the degree catalog |
| Intro-course replacements | Three candidate lecture/lab mappings for Boston BSCS catalogs from 2022–2023 through 2024–2025 |

Current concentrations include 739 program-specific options across 99 program variants. These are eligibility records, including repeated concentrations and elective alternatives, rather than 739 distinct concentrations.

### Requirement review and limitations

Boston **BSCS + Artificial Intelligence concentration, 2026–2027** is the reviewed pilot, together with current NUpath and universitywide rules. Other collected programs and archived editions are labeled as automatically extracted unless their exact source content has been reviewed. Ambiguous requirements remain visible as review items rather than guessed rules.

The app reports **all modeled requirements covered**, not graduation clearance. GPA, some hours-in-major and writing/capstone restrictions, approvals, and complex prose policies still require review. Sample plans provide historical timing hints; actual semester offerings are unverified. CPS, minors, double-major combinations, and graduate degree planning are outside current coverage.

Retired courses remain available for past records, with their archived metadata. Future schedules use current prerequisites and course data. Only registry entries marked `verified` automatically fulfill an older requirement; the checked-in Fundies/OOD mappings are currently **candidates**, pending confirmation of older-catalog applicability and lab fulfillment. Students with approval can record it through **Counts as another course?**. Original course identities and actual credits are preserved.

## Refreshing the data

The checked-in snapshots are sufficient for local startup. `var/courses.db` is generated and ignored by Git; rebuild it after changes to current courses, requirements, or sample-plan data. Archived catalogs and exam policies load directly without a database rebuild. The API and loader use repository-relative absolute paths, so data lookup does not depend on the shell’s working directory.

For an existing checkout with a root-level `courses.db`, move it into `var/` before starting the updated API, or rebuild with `python3 -m backend.db_loader`:

```sh
mkdir -p var
mv courses.db var/courses.db
```

<details>
<summary><b>Refresh courses and sample plans</b></summary>

With the virtual environment active, run from the repository root:

```sh
python json_scrapers/department_scraper.py
python json_scrapers/course_scraper.py
python json_scrapers/plan_scraper.py --catalog-year 2025-2026
python -m backend.db_loader
```

The plan scraper retains the active manifest's edition by default. Use `--current-catalog` to select the live catalog, or `--catalog-year` for an explicit edition. `--output-dir` selects a separate data root and `--delay` controls request pacing.

`data/plan_catalog.json` selects active files and records programs with no published plan. Entries preserve alternatives, bundles, electives, co-op, credits, and source text. Fetch/edition/parsing failures leave the active manifest unchanged. The live 2026–2027 scrape collected zero schedules; switching to it will not silently reuse older plans.

Refreshing current courses also records raw prerequisite text, minimum grades, and exact credit options missing from the older checked-in course-description extraction. Until present, variable-credit choices may be flagged as unverified.

</details>

<details>
<summary><b>Refresh current requirements and concentrations</b></summary>

```sh
python json_scrapers/requirements_scraper.py --catalog-year 2026-2027
python -m backend.db_loader
```

The requirements scraper follows the public sitemap and collects undergraduate bachelor requirements, linked concentrations, universitywide rules, and general-education tabs. It checks robots.txt, paces requests, and preserves ordered sections, source wording, AND/OR structure, credit ranges, elective filters, exclusions, and footnotes. Unsupported tables and ambiguous instructions remain marked for review.

Successful runs publish immutable `data/requirements/<year>/<generation>/` snapshots selected by `data/requirements_catalog.json`. Failures leave the active manifest unchanged; the scrape report records coverage and gaps. The concentration export is derived from requirements, and the database loader reads the active requirement snapshot.

To regenerate only the concentration export from existing data:

```sh
python json_scrapers/concentration_scraper.py
python -m backend.db_loader
```

Extraction is not policy validation. Six references absent from the older local course dataset and an unresolved Family Business concentration link were recorded in the October 13 scrape report.

</details>

<details>
<summary><b>Import archived catalogs and AP/IB policies</b></summary>

```sh
python json_scrapers/archive_requirements_scraper.py --years 2022-2023 2023-2024 2024-2025 2025-2026
python json_scrapers/exam_scraper.py
```

The archive importer follows links within explicitly selected editions, caches public HTML, and publishes complete snapshots under `data/catalogs/<year>/`. Archived degree rules never replace current browsing data or silently become a newer degree catalog.

The exam scraper discovers public AP/IB charts and extracts their PDF tables with pdfplumber. It preserves raw rows, source pages, PDF hashes, and policy versions in `data/exams/`. Ambiguous credit splits or changed score/cap policies stop publication. Older saved versions remain available.

Awarded exam records are resolved again by the backend; estimates do not satisfy requirements or prerequisites. Equivalent course bundles retain their component credits and published NUpath attributes, overlap is counted once, and the combined award is capped at 32 credits. A different admission year requires its own published policy snapshot.

</details>
