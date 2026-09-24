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

Unknown fields are never filled. Opening the popup also remembers values already
selected on the current page. After that, the content script remembers a nonempty
value when a real user leaves or changes the field. It does not record keystrokes.
New exact questions are site-scoped
and default to `review`, so a learned value is available only through the
review checklist. The popup shows each exact question and proposed answer, and
each checked row chooses **All sites**, **This site**, or **This position** before
**Save scope and fill selected** runs. One global answer bank stores the value;
sites retain only their exact control mappings. Cross-site reuse requires an
explicit All sites choice and exact normalized question, kind and option text.
A different existing answer is reported as a conflict and is never overwritten.
Existing text, choice and radio values are also left unchanged.

Native text, number, textarea, select and radio controls are supported. The
Micron/Eightfold custom listbox selector is recognized; a saved answer is filled
only after its open list contains one exact matching option. Its answers are
site- or position-scoped and require review. Checkboxes remain manual because
they commonly express consent. Other platform widgets remain manual until their
option model can be verified. Workday, Greenhouse, Lever, iCIMS, SmartRecruiters
and other ATS adapters can extend the same scanner without separate extensions.

After changing the unpacked extension files, reload its card at
`chrome://extensions` or `edge://extensions` once. Return to the still-open
Micron application and click the extension while the completed form is visible to capture
its existing answers. The form tab itself does not need a reload. The popup
reports the number newly remembered; review
answers remain in the browser's private extension storage.
