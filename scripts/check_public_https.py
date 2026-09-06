"""CI-only Caddy -> Waitress smoke with a temporary local CA, never public ACME.

Requires Docker and the already built retailops:ci image. Cleans only its own
temporary Compose project and volumes. No API credentials or inference calls.
"""
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = 'retailops.example.test'
INVITE = 'ci_synthetic_invite_' + 'a'*40


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def main():
    with tempfile.TemporaryDirectory(prefix='retailops-https-ci-') as folder:
        temp = Path(folder)
        data = temp / 'data'; data.mkdir(); data.chmod(0o777)  # disposable fixture, no real data
        # Keep the directory owned by the runner so it can remove UID-10001 DB files.
        guests = data / 'public-guests'; guests.mkdir(); guests.chmod(0o777)
        compose = (ROOT / 'deploy/compose.public.yaml').read_text().replace('"80:80"', '"127.0.0.1:18080:80"').replace('"443:443"', '"127.0.0.1:18443:443"')
        (temp/'compose.public.yaml').write_text(compose)
        (temp/'Caddyfile').write_text((ROOT/'deploy/Caddyfile').read_text().replace('{$RETAILOPS_PUBLIC_HOST} {', '{$RETAILOPS_PUBLIC_HOST} {\n\ttls internal'))
        (temp/'inference.env').write_text('')
        (temp/'api.env').write_text('RETAILOPS_API_ENABLED=false\n')
        (temp/'deployed.env').write_text('RETAILOPS_IMAGE=retailops:ci\nRETAILOPS_DATA_DIR='+str(data)+'\n')
        (temp/'public.env').write_text('RETAILOPS_PUBLIC_HOST='+HOST+'\nRETAILOPS_PUBLIC_ORIGIN=https://'+HOST+'\nRETAILOPS_PUBLIC_INVITE_TOKEN='+INVITE+'\nRETAILOPS_PUBLIC_CUSTOM_ENABLED=false\n')
        base = ['docker','compose','--project-name','retailops-https-ci-'+str(os.getpid()),
                '--project-directory',str(temp),'--env-file',str(temp/'deployed.env'),
                '--env-file',str(temp/'public.env'),'-f',str(temp/'compose.public.yaml')]
        curl = ['curl','--noproxy','*','--silent','--show-error','--max-time','10',
                '--cacert',str(temp/'root.crt'),'--connect-to',HOST+':443:127.0.0.1:18443']

        def request(path, body=None, jar='alice', origin='https://'+HOST):
            args = curl + ['--cookie',str(temp/(jar+'.cookies')),'--cookie-jar',str(temp/(jar+'.cookies')),
                           '--output',str(temp/'response.json'),'--write-out','%{http_code}',
                           '--dump-header',str(temp/'headers.txt')]
            if body is not None:
                (temp/'request.json').write_text(json.dumps(body))
                args += ['-H','Origin: '+origin,'-H','Content-Type: application/json','--data-binary','@'+str(temp/'request.json')]
            status = int(run(args+['https://'+HOST+path]))
            return status, json.loads((temp/'response.json').read_text())
        try:
            run(base+['config','--quiet'])
            run(base+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','60'])
            for attempt in range(15):
                try:
                    run(base+['cp','caddy:/data/caddy/pki/authorities/local/root.crt',str(temp/'root.crt')])
                    break
                except subprocess.CalledProcessError:
                    if attempt == 14: raise
                    time.sleep(1)
            redirect = run(['curl','--noproxy','*','--silent','--show-error','--max-time','5',
                            '-D','-','-o','/dev/null','-H','Host: '+HOST,'http://127.0.0.1:18080/'])
            assert '308' in redirect and 'https://'+HOST+'/' in redirect
            assert request('/healthz')[1]['hosting'] == 'public-https'
            assert request('/api/orders')[0] == 401
            assert request('/api/login',{'token':INVITE},origin='https://evil.example')[0] == 403
            assert request('/api/login',{'token':INVITE})[0] == 200
            headers = (temp/'headers.txt').read_text().lower()
            assert 'httponly' in headers and 'secure' in headers and 'samesite=strict' in headers
            assert request('/api/orders')[1]['orders'][0]['id'] == 'O-101'
            assert request('/api/orders/O-202')[0] == 404
            assert request('/api/logout',{})[0] == 200
            assert request('/api/orders')[0] == 401
            print('PUBLIC_HTTPS_PROXY_COOKIE_FLOW_OK (temporary test CA; no public certificate or paid inference)')
        except Exception:
            print(run(base+['logs','--tail','40']))  # fixture stack only, contains no real secrets
            raise
        finally:
            run(base+['down','--volumes','--remove-orphans'])


if __name__ == '__main__':
    main()
