"""CI-only actual guest-to-PostgreSQL helper exercise; no real accounts or inference."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from check_public_https import run, ROOT


def main():
    with tempfile.TemporaryDirectory(prefix='retailops-guest-cutover-ci-') as folder:
        temp = Path(folder)
        data = temp/'data'; data.mkdir(); data.chmod(0o777)
        project = 'retailops-cutover-ci-'+str(os.getpid())
        host = 'cutover.example.test'
        compose = (ROOT/'deploy/compose.public.yaml').read_text().replace('"80:80"','"127.0.0.1:18780:80"').replace('"443:443"','"127.0.0.1:18743:443"')
        (temp/'compose.public.yaml').write_text(compose)
        (temp/'Caddyfile').write_text((ROOT/'deploy/Caddyfile').read_text().replace('{$RETAILOPS_PUBLIC_HOST} {','{$RETAILOPS_PUBLIC_HOST} {\n\ttls internal'))
        (temp/'deployed.env').write_text('RETAILOPS_IMAGE=retailops:ci\nRETAILOPS_DATA_DIR='+str(data)+'\n')
        (temp/'public.env').write_text('RETAILOPS_PUBLIC_HOST='+host+'\nRETAILOPS_PUBLIC_ORIGIN=https://'+host+'\nRETAILOPS_PUBLIC_CUSTOM_ENABLED=false\nRETAILOPS_PUBLIC_INVITE_TOKEN='+'a'*40+'\n')
        (temp/'inference.env').write_text(''); (temp/'api.env').write_text('RETAILOPS_API_ENABLED=false\n')
        base = ['docker','compose','--project-name',project,'--project-directory',str(temp),
                '--env-file',str(temp/'deployed.env'),'--env-file',str(temp/'public.env'),'-f',str(temp/'compose.public.yaml')]
        try:
            run(base+['up','-d','--no-build','--pull','never','--wait','--wait-timeout','60','web'])
            run(base+['exec','-T','web','python','-c',
                "from retailops.business.store import BusinessStore; from pathlib import Path; BusinessStore(Path('/data/public-guests/control.sqlite3')).reserve_api_attempt(1)"])
            result = run(['sudo','python3',str(ROOT/'deploy/migrate-public-postgres.py'),
                          '--directory',str(temp),'--host',host,'--project',project])
            assert 'POSTGRES_CUTOVER_OK' in result
            pg = base+['-f',str(temp/'compose.postgres.yaml')]
            check = '''import os
from pathlib import Path
from retailops.config import database_settings
from retailops.identity.postgres import PostgresSessions
from retailops.core import ApiError
s=PostgresSessions(database_settings(os.environ)[1])
secret=Path('/data/access/retailops-owner.code').read_text().strip()
cookie=s.cookie_name+'='+s.login(secret)
with s.resolve(cookie) as binding:
    assert binding.application.store.orders(binding.customer_id)[0]['status']=='pending'
try:
    s.control.reserve_api_attempt(1)
except ApiError as e:
    assert e.code=='api_daily_limit'
else:
    raise AssertionError('Guest API quota was lost')
print('GUEST_POSTGRES_CUTOVER_OK')
'''
            # Root can read the private delivery file; app normally never reads plaintext codes.
            result = run(pg+['exec','-T','--user','0:0','web','python','-c',check])
            assert 'GUEST_POSTGRES_CUTOVER_OK' in result
            assert (data/'public-guests/control.sqlite3').exists()
            print(result.strip())
        except Exception:
            for backup in (temp/'backups').iterdir() if (temp/'backups').exists() else []:
                detail = subprocess.run(['sudo','cat',str(backup/'failure-details.txt')],text=True,capture_output=True)
                print(detail.stdout)
            raise
        finally:
            cleanup = base+['-f',str(temp/'compose.postgres.yaml')] if (temp/'compose.postgres.yaml').exists() else base
            run(cleanup+['down','--volumes','--remove-orphans'])
            run(['sudo','chown','-R',str(os.getuid())+':'+str(os.getgid()),str(temp)])


if __name__ == '__main__':
    main()
