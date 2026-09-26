"""Loopback-only, read-only dashboard for real float training progress."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse


def snapshot(root):
    campaign = None
    campaign_path = root / 'campaign_state.json'
    if campaign_path.exists():
        campaign = json.loads(campaign_path.read_text(encoding='utf-8'))
        active = (root / campaign['active_round']).resolve()
        if active.parent != root.resolve():
            raise ValueError('Campaign round must be a direct child')
        root = active
    runs = []
    for path in sorted(root.glob('*/progress.json')):
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
            state['run_id'] = path.parent.name
            log = root / f'{path.parent.name}.console.log'
            if not log.exists():
                log = path.parent / 'console.log'
            if log.exists():
                state['log_tail'] = log.read_text(encoding='utf-8', errors='replace')[-6000:]
            runs.append(state)
        except (OSError, ValueError):
            continue
    manager = root / 'experiment_status.json'
    summary = json.loads(manager.read_text(encoding='utf-8')) if manager.exists() else {}
    if summary.get('status') == 'failed':
        for state in runs:
            if state['run_id'] == summary.get('active_run'):
                state.update(status='failed', message=summary.get('message', 'Manager failed'))
    return {'runs': runs, 'summary': summary, 'campaign': campaign,
            'server_time': datetime.now(timezone.utc).isoformat()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8770)
    args = parser.parse_args()
    root = args.root.resolve()
    html_path = Path(__file__).with_name('training_dashboard.html')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlparse(self.path).path
            if route == '/':
                content, kind = html_path.read_bytes(), 'text/html; charset=utf-8'
            elif route == '/api/progress':
                content, kind = json.dumps(snapshot(root), ensure_ascii=False).encode(), 'application/json; charset=utf-8'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, *_):
            pass

    print(f'Training dashboard: http://127.0.0.1:{args.port}/', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()
