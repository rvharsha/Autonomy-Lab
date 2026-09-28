"""Declared delay on real PostgreSQL reads, confined to the disposable fixture."""

import json
import sys
import time
import uuid
from pathlib import Path

import psycopg

from autonomy_lab.harness import save
from autonomy_lab.kubernetes import ROOT, command
from autonomy_lab.procedures import require
from experiments.experience_learning.run import control as existing_control
from experiments.generated_policy.runtime import remove_container

DEFINITION = ''' SELECT p.sku,
    p.unit_price_minor,
    p.stock,
    p.currency
   FROM products_data p
     CROSS JOIN ( SELECT pg_sleep(0.05::double precision) AS pg_sleep) latency;'''
DDL = '''ALTER TABLE products RENAME TO products_data;
CREATE VIEW products AS SELECT p.* FROM products_data p CROSS JOIN (SELECT pg_sleep(0.05)) latency;
GRANT SELECT ON products TO inventory_reader, verifier_reader;'''


def verify_definition(definition):
    # pg_get_viewdef can parenthesize the numeric cast differently by PG version.
    # Preserve every identifier, literal, operator and column; ignore formatting.
    def normalized(value):
        return ''.join(value.split()).replace('(', '').replace(')', '')
    require(normalized(definition) == normalized(DEFINITION), 'Declared read-delay view changed')


def install_delay(db):
    with psycopg.connect(db, autocommit=True, connect_timeout=3,
                        options='-c statement_timeout=1000') as connection:
        # Transactional DDL prevents leaving a half-created view after failure.
        with connection.transaction():
            connection.execute(DDL)
        verify_delay(connection)


def verify_delay(connection):
    definition = connection.execute("SELECT pg_get_viewdef('products'::regclass, true)").fetchone()[0]
    verify_definition(definition)
    return definition


def control(kube, db, phase, capacity):
    result = existing_control(kube, db, phase, capacity)
    with psycopg.connect(db, autocommit=True, connect_timeout=3,
                        options='-c statement_timeout=1000') as connection:
        result['read_delay_view'] = verify_delay(connection)
    return result


def check(destination):
    """Real pinned-Postgres engineering probe; no service or learning samples."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    record = {'kind': 'authored_database_probe_not_service_outcomes', 'status': 'started'}
    save(destination, record)
    name = 'autolab-delay-probe-' + uuid.uuid4().hex[:12]
    try:
        image = json.loads((ROOT / 'infra/toolchain.json').read_text())['postgres_image']
        command(['docker', 'run', '--rm', '-d', '--name', name, '--network=none', '--memory=256m',
                 '--cpus=1', '-e', 'POSTGRES_PASSWORD=lab-test-only', '-e', 'POSTGRES_DB=lab', image], timeout=240)
        deadline = time.monotonic() + 60
        while True:
            try:
                # The image uses a temporary Unix-only server during initdb.
                # TCP readiness identifies the final server, after database setup.
                command(['docker', 'exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', 'postgres', '-d', 'lab'], timeout=5)
                break
            except RuntimeError:
                require(time.monotonic() < deadline, 'Probe database unavailable')
                time.sleep(.2)

        def sql(value):
            return command(['docker', 'exec', '-i', name, 'psql', '-X', '-qAt', '-U', 'postgres', '-d', 'lab',
                            '-v', 'ON_ERROR_STOP=1'], input=value, timeout=10).strip()

        sql((ROOT / 'fixtures/database.sql').read_text())
        sql('BEGIN;\n' + DDL + '\nCOMMIT;')
        definition = sql("SELECT pg_get_viewdef('products'::regclass, true);")
        verify_definition(definition)
        actual = json.loads(sql("SET ROLE inventory_reader; SELECT row_to_json(p) FROM products p WHERE sku='bolt';"))
        require(actual == {'sku': 'bolt', 'unit_price_minor': 125, 'stock': 100, 'currency': 'USD'}, 'Probe changed product semantics')
        measurement = json.loads(sql("SET ROLE inventory_reader; EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM products WHERE sku='bolt';"))[0]
        require(40 <= measurement['Execution Time'] < 2500, 'Delay not established or query exceeded bound')
        record.update(status='complete', image=image, definition=definition, query_ms=measurement['Execution Time'])
    except BaseException as error:
        record.update(status='failed', error_type=type(error).__name__)
        raise
    finally:
        try:
            remove_container(name)
            record['cleanup'] = 'confirmed_absent'
        except Exception as error:
            record.update(status='failed', cleanup_error_type=type(error).__name__)
            raise
        finally:
            save(destination, record)


if __name__ == '__main__':
    check(Path(sys.argv[1]))
