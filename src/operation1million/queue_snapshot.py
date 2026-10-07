"""Private, disposable queue snapshots; the ledger and index remain authoritative."""
import hashlib
import json
from pathlib import Path
import tempfile


class QueueSnapshot:
    def __init__(self, ledger, db):
        self.path = Path(ledger).with_name('review_queue.cache.json')
        source = Path(__file__).parent
        config = source.parents[1] / 'data/config'
        digest = hashlib.sha256()
        for item in sorted(source.glob('*.py')) + sorted(config.glob('*.toml')):
            digest.update(item.name.encode())
            digest.update(item.read_bytes())
        self.identity = [1, str(Path(ledger).resolve()), str(Path(db).resolve()), digest.hexdigest()]
        self.saved = None

    def signature(self, key, links):
        return json.dumps([self.identity, key, links], default=str, separators=(',', ':'))

    def load(self, signature):
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
            state = value['state']
            if value['signature'] != signature or not isinstance(state, dict):
                return None
            if not all(isinstance(state.get(name), list) for name in ('pending', 'backlog', 'applied', 'skipped')):
                return None
            for name in ('pending', 'backlog', 'applied', 'skipped'):
                if any(not isinstance(group, dict) or not isinstance(group.get('id'), str)
                       or not all(isinstance(group.get(key), str) for key in ('company', 'title'))
                       or not isinstance(group.get('confidence'), (int, float))
                       or not isinstance(group.get('jobs'), list)
                       or not group['jobs']
                       or not all(isinstance(job, dict) and isinstance(job.get('url'), str)
                                  and job['url'] for job in group['jobs']) for group in state[name]):
                    return None
            self.saved = signature
            return state
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, signature, state):
        if self.saved == signature:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='review-queue-', suffix='.tmp', delete=False) as handle:
                temporary = Path(handle.name)
                json.dump({'signature': signature, 'state': state}, handle, separators=(',', ':'))
            temporary.replace(self.path)
            self.saved = signature
        except (OSError, TypeError, ValueError) as exc:
            # A cache failure must never prevent reading or writing the real ledger.
            print(f'Review queue cache unavailable: {exc}', flush=True)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
