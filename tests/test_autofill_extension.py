"""Static safety contracts for the standalone browser extension."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'application-autofill' / 'extension'


class AutofillExtensionTests(unittest.TestCase):
    def test_manifest_has_only_user_invoked_page_access(self):
        manifest = json.loads((EXTENSION / 'manifest.json').read_text())
        self.assertNotIn('host_permissions', manifest)
        self.assertNotIn('content_scripts', manifest)
        self.assertEqual(set(manifest['permissions']), {'activeTab', 'scripting', 'storage'})

    def test_profile_is_local_and_runtime_has_no_bridge_or_token_prompt(self):
        popup = (EXTENSION / 'popup.html').read_text()
        script = (EXTENSION / 'popup.js').read_text()
        ignore = (ROOT / '.gitignore').read_text()
        self.assertNotIn('Local bridge token', popup)
        self.assertNotIn('127.0.0.1', script)
        self.assertIn("chrome.runtime.getURL('local-profile.json')", script)
        self.assertIn('/application-autofill/extension/local-profile.json', ignore)

    def test_sensitive_and_consent_controls_remain_manual(self):
        source = (EXTENSION / 'content.js').read_text()
        for marker in ('password', 'checkbox', 'social security', 'signature', 'consent'):
            self.assertIn(marker, source)
        self.assertNotIn('.submit(', source)

    def test_popup_is_one_click_and_unknown_values_are_not_filled(self):
        popup = (EXTENSION / 'popup.html').read_text()
        script = (EXTENSION / 'popup.js').read_text()
        self.assertNotIn('Scan page', popup)
        self.assertNotIn('Record current page', popup)
        self.assertIn('Rescan and fill known answers', popup)
        self.assertIn('Unknown fields stay empty', popup)
        self.assertIn('run(fillKnown)', script)
        self.assertIn("status: 'unknown'", script)

    def test_learning_records_only_final_trusted_events(self):
        source = (EXTENSION / 'content.js').read_text()
        self.assertIn('answerCaptures', source)
        self.assertIn("document.addEventListener('change', rememberFinalValue, true)", source)
        self.assertIn("document.addEventListener('blur', rememberFinalValue, true)", source)
        self.assertNotIn("document.addEventListener('input', rememberFinalValue", source)
        self.assertIn('if (!event.isTrusted) return', source)

    def test_learned_answers_require_review_and_conflicts_are_preserved(self):
        script = (EXTENSION / 'popup.js').read_text()
        self.assertIn("policy: 'review'", script)
        self.assertIn('summary.conflicts += 1', script)
        self.assertNotIn('field.answer = control.value;\n        summary.conflicts', script)

    def test_existing_choices_are_not_overwritten(self):
        source = (EXTENSION / 'content.js').read_text()
        self.assertIn('radios.some(item => item.checked)', source)
        self.assertIn('if (current.length) return', source)
        self.assertIn("return 'occupied'", source)

    def test_review_answers_are_visible_and_individually_selected(self):
        popup = (EXTENSION / 'popup.html').read_text()
        script = (EXTENSION / 'popup.js').read_text()
        self.assertIn('Review before filling', popup)
        self.assertIn('Save scope and fill selected', popup)
        self.assertIn("item.status === 'requires_review'", script)
        self.assertIn('selected.has(item.question_id)', script)
        self.assertIn('answer.textContent = displayAnswer(item.answer)', script)

    def test_review_scope_controls_single_shared_answer_bank(self):
        popup = (EXTENSION / 'popup.html').read_text()
        script = (EXTENSION / 'popup.js').read_text()
        self.assertNotIn('database', popup.lower())
        for label in ('All sites', 'This site', 'This position'):
            self.assertIn(label, script)
        self.assertIn("field.reuse_scope = scope", script)
        self.assertIn("field.reuse_signature = questionSignature(question)", script)
        self.assertIn("const groups = ['position', 'site', 'global']", script)
        self.assertIn("binding: builtinKey ? 'builtin' : (fieldKey ? 'reused' : null)", script)


if __name__ == '__main__':
    unittest.main()
