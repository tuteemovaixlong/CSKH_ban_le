"""CI-only Caddy -> Waitress smoke with a temporary local CA, never public ACME.

Requires Docker and the already built retailops:ci image. Cleans only its own
temporary Compose project and volumes. No API credentials or inference calls.
"""
import json
import os
import subprocess
import shutil
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
        for folder in (data/'persistent', data/'persistent'/'tenants'):
            folder.mkdir(); folder.chmod(0o777)
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

        def request(path, body=None, jar='alice', origin='https://'+HOST, headers=()):
            args = curl + ['--cookie',str(temp/(jar+'.cookies')),'--cookie-jar',str(temp/(jar+'.cookies')),
                           '--output',str(temp/'response.json'),'--write-out','%{http_code}',
                           '--dump-header',str(temp/'headers.txt')]
            if body is not None:
                (temp/'request.json').write_text(json.dumps(body))
                args += ['-H','Origin: '+origin,'-H','Content-Type: application/json','--data-binary','@'+str(temp/'request.json')]
            for header in headers:
                args += ['-H', header]
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
            for asset in ('app.js', 'styles.css', 'chat-focus.js', 'chat-focus.css'):
                actual = run(curl + ['--fail', 'https://' + HOST + '/' + asset])
                assert actual == (ROOT/'web'/asset).read_text(), asset
            print('PUBLIC_UI_ASSETS_OK (four same-origin assets through Caddy)')
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
            # Provision through the packaged operator CLI, then switch the same HTTPS stack.
            admin = base+['exec','-T','web','python','-m','retailops','identity']
            run(admin+['init-tenant','--tenant','ci-shop','--name','CI shop','--seed-demo'])
            member = json.loads(run(admin+['create-member','--tenant','ci-shop','--principal','ci-viewer',
                '--name','CI viewer','--customer','C-002','--role','viewer']))['membership_id']
            run(admin+['issue-credential','--membership',member,'--credential-file','/tmp/ci-account-code'])
            code = run(base+['exec','-T','web','cat','/tmp/ci-account-code']).strip()
            with (temp/'public.env').open('a') as config:
                config.write('RETAILOPS_DATA_MODE=persistent-demo\n')
            run(base+['up','-d','--no-build','--pull','never','--force-recreate','--wait','--wait-timeout','60','web'])
            assert request('/healthz')[1]['data_mode'] == 'persistent-demo'
            assert request('/api/login',{'token':INVITE})[0] == 401
            assert request('/api/login',{'token':code},jar='account')[0] == 200
            assert request('/api/session',jar='account')[1]['role'] == 'viewer'
            assert request('/api/orders',jar='account')[1]['orders'][0]['id'] == 'O-202'
            assert request('/api/orders/O-101',jar='account')[0] == 404
            assert request('/api/cancellation-proposals',{'order_id':'O-202','order_version':1,
                'cancel_reason':'ordered_by_mistake'},jar='account')[0] == 403
            assert request('/api/logout',{},jar='account')[0] == 200
            run(base+['restart','web'])
            # Compose --wait handles readiness after the restart, without contacting a model.
            run(base+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','60','web'])
            assert request('/api/login',{'token':code},jar='account')[0] == 200
            assert request('/api/orders',jar='account')[1]['orders'][0]['id'] == 'O-202'
            print('PERSISTENT_HTTPS_ACCOUNT_FLOW_OK (packaged CLI, isolation, roles, restart)')
            # Cancel an order before moving the stopped SQLite workspace to PostgreSQL.
            run(admin+['set-role','--membership',member,'--role','customer'])
            assert request('/api/login',{'token':code},jar='account')[0] == 200
            proposal = request('/api/cancellation-proposals',{'order_id':'O-202','order_version':1,
                'cancel_reason':'ordered_by_mistake'},jar='account')[1]
            assert request('/api/cancellation-proposals/'+proposal['proposal_id']+'/confirm',{'confirmed':True},
                jar='account',headers=['Idempotency-Key: ci-postgres-migration'])[0] == 200
            for name in ('compose.postgres.yaml','init-postgres.sh'):
                shutil.copy2(ROOT/'deploy'/name,temp/name)
            run(['python3',str(ROOT/'deploy/configure-postgres.py'),'--directory',str(temp)])
            pgbase = base+['-f',str(temp/'compose.postgres.yaml')]
            run(pgbase+['up','-d','--wait','--wait-timeout','90','postgres'])
            run(base+['stop','web'])
            run(pgbase+['run','--rm','--no-deps','--entrypoint','python','web','-m','retailops','database',
                        'import-sqlite','--offline-snapshot','/data/persistent'])
            run(pgbase+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','60','web'])
            assert request('/healthz')[1]['storage_backend'] == 'postgresql'
            assert request('/api/orders',jar='account')[0] == 401
            assert request('/api/login',{'token':code},jar='account')[0] == 200
            assert request('/api/orders',jar='account')[1]['orders'][0]['status'] == 'cancelled'
            assert request('/api/orders/O-101',jar='account')[0] == 404
            # Runtime credentials must be the limited application role, never the bootstrap superuser.
            flags = run(pgbase+['exec','-T','postgres','psql','-U','postgres','-d','retailops','-Atc',
                "SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname='retailops'"]).strip()
            assert flags == 'f'
            # Database extensions are infrastructure, not tenant/application data. Dump only
            # the RetailOps-owned schemas, bootstrap pgvector as postgres in the target DB,
            # then restore all application objects as the limited retailops role.
            dump = run(pgbase+['exec','-T','postgres','pg_dump','-U','postgres','-d','retailops',
                '--no-owner','--no-acl','--schema=retailops_identity','--schema=tenant_*'])
            run(pgbase+['exec','-T','postgres','createdb','-U','postgres','-O','retailops','retailops_restore'])
            extension_sql = """CREATE SCHEMA retailops_extensions AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA retailops_extensions FROM PUBLIC;
GRANT USAGE ON SCHEMA retailops_extensions TO retailops;
CREATE EXTENSION vector WITH SCHEMA retailops_extensions;
"""
            run(pgbase+['exec','-T','postgres','psql','-U','postgres','-d','retailops_restore',
                '-v','ON_ERROR_STOP=1'], input=extension_sql)
            run(pgbase+['exec','-T','postgres','psql','-U','retailops','-d','retailops_restore',
                '-v','ON_ERROR_STOP=1'], input=dump)
            extension = run(pgbase+['exec','-T','postgres','psql','-U','postgres','-d','retailops_restore','-Atc',
                "SELECT n.nspname||':'||e.extversion FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace WHERE e.extname='vector'"]).strip()
            assert extension.startswith('retailops_extensions:')
            restored = run(pgbase+['exec','-T','web','python','-c',
                "from retailops.config import database_settings; import os; from psycopg.conninfo import make_conninfo; "
                "from retailops.identity.postgres import PostgresSessions; "
                "s=PostgresSessions(make_conninfo(database_settings(os.environ)[1],dbname='retailops_restore')); "
                "assert s.business_store('ci-shop').orders('C-002')[0]['status']=='cancelled'; print('RESTORE_OK')"])
            assert 'RESTORE_OK' in restored
            print('POSTGRES_HTTPS_IMPORT_RESTORE_OK (limited DB role; pgvector prebootstrapped; no external inference)')
        except Exception:
            print(run(base+['logs','--tail','40']))  # fixture stack only, contains no real secrets
            raise
        finally:
            cleanup_base = base+['-f',str(temp/'compose.postgres.yaml')] if (temp/'compose.postgres.yaml').exists() else base
            run(cleanup_base+['down','--volumes','--remove-orphans'])
            if (temp/'postgres-secrets').exists():
                shutil.rmtree(temp/'postgres-secrets')


if __name__ == '__main__':
    main()
