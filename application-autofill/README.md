# Application autofill

This standalone folder contains an unpacked Chrome/Edge extension. It keeps its
working answer profile in private extension storage and is inert until its popup
is opened on a page. It has no background process, startup entry, local server or
terminal window.
It never submits an application, uploads a file, enters a password, accepts an
agreement, solves a challenge, or overwrites a nonempty text field.

## Install

1. Open `chrome://extensions` or `edge://extensions`, enable Developer mode,
   choose **Load unpacked**, and select the `extension` directory beside this
   file.
2. Open an HTTPS application page and click the extension. It scans and fills
   exact safe matches immediately; no terminal, file launcher, service or pairing
   prompt is required.

The ignored `extension/local-profile.json` file seeds the first browser-local
profile from the workstation answer bank. `prepare-profile.py` refreshes that
seed for a new browser profile; normal extension use never runs it. Answers
recorded by the extension remain in `chrome.storage.local` for that browser
profile.

Unknown fields are never filled. After the popup has been opened on a page, the
content script remembers a nonempty value only when a real user leaves or changes
that field. It does not record keystrokes. New exact questions are site-scoped
and retain `review` policy metadata. The user's automatic-fill setting permits
known compatible values to be filled immediately; disabling it restores the
review checklist. In checklist mode, each checked row chooses **All sites**,
**This site**, or **This position** before **Save scope and fill selected** runs.
One answer bank stores the value;
sites retain only their exact control mappings. Cross-site reuse requires an
explicit All sites choice and exact normalized question, kind and option text.
A different existing answer is reported as a conflict and is never overwritten.
Existing text, choice and radio values are also left unchanged.

The native scanner is ATS-independent and supports text, number, textarea,
select, and radio controls. Checkboxes remain manual because they commonly
express consent. Platform-specific widgets that do not expose native controls
remain manual until an adapter can verify their option model rather than merely
type text. Workday, Greenhouse, Lever, iCIMS, SmartRecruiters and other ATS
adapters can extend the same scanner without creating separate extensions.

After updating to 0.5.0, reload the unpacked extension and refresh any application
page where its previous content script was already installed. The scanner now
checks inherited visibility and disabled state, isolates radio groups by their
HTML form owner, and verifies a complete unambiguous choice before selecting it.
It rechecks the scanned question and position before filling a dynamic page.

Version 0.5.0 adds a Workday/Greenhouse/Lever adapter registry, an explicit
known-answer assessment engine, a browser-local basic-question setup page and
owned accessible single-choice/searchable listboxes. Degree, major and graduation
fields remain separate. Canonical full school names take priority over approved
abbreviations. The user requested filling every known matching answer, so the
setup preference now defaults to automatic filling, including stored review
answers; turn that preference off to restore the individual checklist. Unknown,
ambiguous and context-dependent answers stay empty until their meaning/context is
supplied. The popup's matching report gives a reason for each decision.
See [the framework contract](../docs/autofill-framework.md) for capabilities,
limitations and researched GitHub/official ATS sources.

## Offline DOM regression tests

The Python suite includes optional Node/jsdom tests of the actual extension
scripts using fictional forms, values and sites. Install the test-only runtime:

```text
npm install --prefix .local/audit-node --no-package-lock --no-audit --no-fund jsdom@22.1.0
python -m unittest discover -s tests -p test_autofill_runtime.py -v
```

Node/jsdom are not required to use the extension or run the VPS. When absent,
the DOM suite reports a skip rather than claiming browser behavior was tested.
