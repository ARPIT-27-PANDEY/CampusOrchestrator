# Demo script (about 8 minutes)

Run locally (see the README) with the mock provider, or with `LLM_PROVIDER=groq`. For step 6 start the
backend with `ALLOW_FAULT_INJECTION=true`. Open http://localhost:3000 and use the *Ask* page.
Avoid real personal data in questions and screenshots.

1. **Open-access books.** *"Find open access books on calculus."* -> Library `discover_public_books`
   (`open_access_only=true`). The answer lists OpenStax *Calculus Volume 1/2* as `open access download`
   and says it is **not** the campus library. Point out the access types (download / read / borrow /
   preview / metadata only) and that a failing provider is reported, not hidden.
2. **Topic search in the campus catalogue.** *"Do you have books about mechanics?"* -> `search_books`
   matched on subject (mechanics -> statics, dynamics) then `get_book_availability`. The source tag says
   *Demo data*: holdings are synthetic; the bibliographic record links to Open Library.
3. **Cuisine-filtered lunch.** *"Suggest a vegetarian lunch today"* or *"Any south indian food today?"*
   -> `get_menu_for_date` with the **campus** date and filters; the answer shows the weekday and rotation
   week the tool returned. All menu data is labelled demo.
4. **Events today in India.** *"What events are happening today?"* -> `get_events_for_date` with today's
   IST date (the sidebar shows campus time). Mention the 18:29Z/18:30Z boundary tests. Then *"Is Diwali a
   holiday?"* -> the official Autumn 2026-27 calendar record (origin *official*, document + page).
5. **Official regulation with a citation.** *"What is the attendance policy?"* -> Academics cites the
   2024 Senate notification and/or UG Ordinances 2025 p. 32; expand the citation for the excerpt, version
   hash and official URL. Then *"What is the penalty for carrying prohibited items repeatedly in exams?"*
   -> the 2026 revision ranks first and the applicability note says the 2025 guidelines are superseded.
6. **One server unavailable.** Under *Failure testing* choose **Events** and ask *"What events are
   happening today and what are the library hours today?"* -> partial answer: Library hours arrive, the
   notice says *Events: is unreachable* and that this was not treated as "no results".
7. **Hashing vs semantic retrieval.** On *Evaluation*, section 2-3: Recall@5 / MRR for hashing, FastEmbed
   and hybrid on the same 50 test questions, thresholds tuned on dev only.
8. **A historical run with its configuration.** In section 1 pick another run (e.g. the FastEmbed agent
   run) and *Compare with* the default run: metric deltas, regressions/improvements, and the recorded
   provider, prompt hash, tool-schema hash, dataset sha, retriever and commit.
