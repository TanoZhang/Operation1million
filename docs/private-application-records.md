# Private application records

The application-autofill extension, Python answer bank and job-answers CLI were
removed on 2026-10-04 at the user's request. Old local autofill copies were
deleted without a migration archive. Muse's existing job-applications/ records
in the private Operation1million-data repository were checked and left unchanged.
The private profile was already more complete than the old local copies.

Continue using the private folder's existing README, profile.json,
questions.json and application-rules.md. Personal details, answers, resumes and
application history must never be copied into the public code repository.
The collector/review deployment does not load these personal profiles.

Browser extension storage was not inspected or modified. If the unpacked
extension remains registered, remove it through the browser's Extensions page;
deleting repository source does not uninstall an extension from the browser.
