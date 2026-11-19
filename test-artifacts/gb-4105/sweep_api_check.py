import sys, os
sys.path.insert(0, '/workspace/backend')
os.environ.setdefault('JWT_SECRET', 'test-secret')
import src.services.sweeps as sw
from src.config.database import Base, engine, Session
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.trace import Trace
from src.models.identity import User, Audit
from src.models.sweep import Sweep
from src.utils.security import hash_password
from fastapi.testclient import TestClient
import src.main as main


class Q:
    items = []

    def rpush(self, *a):
        Q.items.append(a)
        return 1

    def ping(self):
        return True


sw.queue = Q()
main.queue = Q()
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

steps = [{'op': 'scan', 'source': 'readings'},
         {'op': 'filter', 'field': 'value', 'compare': 'gte', 'value': 50},
         {'op': 'hash_join', 'right': 'sensors', 'left_key': 'sensor_id', 'right_key': 'sensor_id'},
         {'op': 'group', 'keys': ['zone'], 'measure': 'value', 'aggregate': 'avg'}]
sensors = [{'sensor_id': 1, 'zone': '北场', 'device_type': 'pump'},
           {'sensor_id': 2, 'zone': '南场', 'device_type': 'pump'}]
readings = [{'sensor_id': 1, 'value': 10.0, 'recorded_at': 'a'},
            {'sensor_id': 2, 'value': 20.0, 'recorded_at': 'b'},
            {'sensor_id': 1, 'value': 30.0, 'recorded_at': 'c'}]
with Session() as s:
    for role in ('admin', 'operator', 'viewer'):
        s.add(User(email=role + '@x', role=role, password=hash_password('pw')))
    d = Dataset(name='api-ds', sensors=sensors, readings=readings)
    s.add(d)
    s.flush()
    p = Plan(name='api-plan', dataset_id=d.id, steps=steps)
    s.add(p)
    s.flush()
    t = Trace(name='api-trace', plan_id=p.id, dataset_id=d.id, status='completed',
              snapshot={'dataset': {'name': 'api-ds', 'sensors': sensors, 'readings': readings},
                        'plan': {'steps': steps}})
    s.add(t)
    s.commit()
    tid = t.id

client = TestClient(main.app)


def login(role):
    r = client.post('/auth/login', json={'email': role + '@x', 'password': 'pw'})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


op = login('operator')
viewer = login('viewer')
anon = client.get('/sweeps')
assert anon.status_code == 401, anon.status_code
assert client.get('/sweeps', headers=viewer).status_code == 200

r = client.post('/sweeps', json={'trace_id': tid, 'step_index': 1, 'name': ''}, headers=viewer)
assert r.status_code == 403, r.text
r = client.post('/sweeps', json={'trace_id': tid, 'step_index': 0, 'name': ''}, headers=op)
assert r.status_code == 400, r.text
assert '数值范围' in r.json()['detail'], r.json()
r = client.post('/sweeps', json={'trace_id': 999, 'step_index': 1, 'name': ''}, headers=op)
assert r.status_code == 404, r.json()
r = client.post('/sweeps', json={'trace_id': tid, 'step_index': 1, 'name': ''}, headers=op)
assert r.status_code == 200, r.text
sweep = r.json()
assert sweep['status'] == 'queued' and sweep['pending_count'] == sweep['total_intervals'] > 0
assert sweep['coverage_complete'] is False
r = client.post('/sweeps', json={'trace_id': tid, 'step_index': 1, 'name': sweep['name']}, headers=op)
assert r.status_code == 409, r.text

listed = client.get('/sweeps', headers=viewer).json()
assert listed and listed[0]['id'] == sweep['id'] and 'intervals' not in listed[0]
detail = client.get(f"/sweeps/{sweep['id']}", headers=viewer).json()
assert detail['intervals'] and all(i['status'] == 'pending' for i in detail['intervals'])
assert detail['field'] == 'value' and detail['compare'] == 'gte'

# the worker consumes the queue: simulate it
sw.run(sweep['id'])
detail = client.get(f"/sweeps/{sweep['id']}", headers=viewer).json()
assert detail['status'] == 'completed' and detail['coverage_complete'] is True
assert detail['pending_count'] == 0 and detail['published_count'] >= 1
assert detail['groups'], detail
for g in detail['groups']:
    assert g['operators'] and g['checksum'] and set(g['member_indexes']) == set(range(g['member_indexes'][0], g['member_indexes'][-1] + 1))

# idempotent resume on a completed sweep
r = client.post(f"/sweeps/{sweep['id']}/resume", headers=op)
assert r.status_code == 200 and r.json()['status'] == 'completed'

assert any(a[1] == sweep['id'] for a in Q.items), Q.items
print('API CHECK PASS', detail['published_count'], detail['merged_count'], detail['total_intervals'])
