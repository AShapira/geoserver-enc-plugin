"""Loopback HTTP interface for the catalog manager."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sqlite3

from catalog_manager import PROJECT, initialize, save_provider, start_job, state


def serve(root, port):
    root = root.expanduser().resolve()
    initialize(root)

    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, body, content_type='application/json'):
            if content_type == 'application/json':
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def local(self):
            host = self.headers.get('Host')
            port = self.server.server_port
            allowed = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if port == 80:
                allowed.update(('127.0.0.1', 'localhost'))
            if host in allowed and self.headers.get('Origin', f'http://{host}') == f'http://{host}':
                return True
            self.reply(403, {'error': 'Open the local manager address shown in the terminal'})
            return False

        def do_GET(self):
            if not self.local():
                return
            assets = {'/': ('index.html', 'text/html'), '/manager.css': ('manager.css', 'text/css'),
                      '/manager.js': ('manager.js', 'text/javascript')}
            if self.path in assets:
                name, mime = assets[self.path]
                self.reply(200, (PROJECT/'manager'/name).read_bytes(), mime)
            elif self.path == '/api/state':
                self.reply(200, state(root))
            elif match := re.fullmatch(r'/api/logs/([0-9a-f]{32})', self.path):
                path = root/'logs'/(match[1]+'.log')
                if path.is_file():
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 32768))
                        self.reply(200, {'log': stream.read().decode(errors='replace')})
                else:
                    self.reply(404, {'error': 'Job log unavailable'})
            else:
                self.reply(404, {'error': 'Unknown page'})

        def do_POST(self):
            if not self.local():
                return
            try:
                size = int(self.headers.get('Content-Length', 0))
                if self.headers.get_content_type() != 'application/json' or not 0 < size <= 16384:
                    raise ValueError('Expected a JSON request')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
                    raise ValueError('Expected text fields')
                if self.path == '/api/providers':
                    key = save_provider(root, body['location'], body.get('name', ''), body.get('id'))
                elif self.path == '/api/jobs':
                    key = start_job(root, body['provider'], body['action'], body.get('snapshot'))
                else:
                    self.reply(404, {'error': 'Unknown action'})
                    return
                self.reply(201, {'id': key})
            except BlockingIOError:
                self.reply(409, {'error': 'Another catalog job is running'})
            except (ValueError, KeyError, OSError, sqlite3.Error) as error:
                self.reply(400, {'error': str(error)})

        def log_message(self, fmt, *args):
            if args and str(args[0]).startswith('GET') and len(args) > 1 and str(args[1]) == '200':
                return
            super().log_message(fmt, *args)

    with ThreadingHTTPServer(('127.0.0.1', port), Handler) as server:
        print(f'ENC catalog manager: http://127.0.0.1:{server.server_port}/', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
