import sys
sys.path.insert(0, '/workspace/backend')
import src.services.sweeps as sw
from src.config.database import Base, engine, Session
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.trace import Trace
from src.models.identity import User, Audit
from src.models.sweep import Sweep
from src.schemas.business import SweepInput


class Q:
    items = []

    def rpush(self, *a):
        Q.items.append(a)
        return 1


sw.queue = Q()
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

steps = [{'op': 'scan', 'source': 'readings'},
         {'op': 'filter', 'field': 'value', 'compare': 'gte', 'value': 50},
         {'op': 'hash_join', 'right': 'sensors', 'left_key': 'sensor_id', 'right_key': 'sensor_id'},
         {'op': 'group', 'keys': ['zone'], 'measure': 'value', 'aggregate': 'avg'}]
sensors = [{'sensor_id': 1, 'zone': '北场', 'device_type': 'pump'},
           {'sensor_id': 2, 'zone': '南场', 'device_type': 'pump'}]
# sensor 99 has no matching sensor row: its readings are dropped by the join,
# so thresholds that only exclude sensor-99 rows produce identical group results.
readings = [{'sensor_id': 1, 'value': 10.0, 'recorded_at': 'a'},
            {'sensor_id': 2, 'value': 20.0, 'recorded_at': 'b'},
            {'sensor_id': 99, 'value': 30.0, 'recorded_at': 'c'},
            {'sensor_id': 99, 'value': 40.0, 'recorded_at': 'd'}]

with Session() as s:
    d = Dataset(name='merge-ds', sensors=sensors, readings=readings)
    s.add(d)
    s.flush()
    p = Plan(name='merge-plan', dataset_id=d.id, steps=steps)
    s.add(p)
    s.flush()
    t = Trace(name='merge-trace', plan_id=p.id, dataset_id=d.id, status='completed',
              snapshot={'dataset': {'name': 'merge-ds', 'sensors': sensors, 'readings': readings},
                        'plan': {'steps': steps}})
    s.add(t)
    s.flush()
    # aggregate-stage filter variant on the same snapshot
    agg_steps = steps + [{'op': 'filter', 'field': 'avg', 'compare': 'gte', 'value': 0}]
    agg_readings = [{'sensor_id': 1, 'value': 60.0, 'recorded_at': 'a'},
                    {'sensor_id': 2, 'value': 70.0, 'recorded_at': 'b'}]
    t2 = Trace(name='agg-trace', plan_id=p.id, dataset_id=d.id, status='completed',
               snapshot={'dataset': {'name': 'merge-ds', 'sensors': sensors, 'readings': agg_readings},
                         'plan': {'steps': agg_steps}})
    s.add(t2)
    s.commit()
    tid, tid2 = t.id, t2.id

print('== merge test ==', flush=True)
r = sw.create(SweepInput(trace_id=tid, step_index=1, name='merge-sweep'))
sw.run(r['id'])
d = sw.detail(r['id'])
print(d['status'], 'complete', d['coverage_complete'], 'published', d['published_count'], 'merged', d['merged_count'])
for i in d['intervals']:
    print(' ', i['index'], i['status'], i['threshold'], 'into', i['merged_into'], 'rows', i['output_rows'])
print('groups', [(g['root_index'], g['lower'], g['upper'], g['lower_inclusive'], g['upper_inclusive'], g['member_indexes']) for g in d['groups']])
assert d['status'] == 'completed' and d['coverage_complete']
assert d['merged_count'] == 2, d['merged_count']
group = [g for g in d['groups'] if len(g['member_indexes']) == 3]
assert group and group[0]['member_indexes'] == [2, 3, 4], group
print('merge ok', flush=True)

print('== aggregate-stage filter sweep ==', flush=True)
r2 = sw.create(SweepInput(trace_id=tid2, step_index=4, name='agg-sweep'))
sw.run(r2['id'])
d2 = sw.detail(r2['id'])
print(d2['status'], [(i['index'], i['status'], i['threshold'], i['output_rows']) for i in d2['intervals']])
assert d2['status'] == 'completed' and d2['intervals'][0]['threshold'] == 60.0
assert d2['intervals'][-1]['output_rows'] == 0
print('aggregate sweep ok', flush=True)

print('== resume after interruption ==', flush=True)
r3 = sw.create(SweepInput(trace_id=tid, step_index=1, name='resume-sweep'))
# simulate a crash after two intervals were confirmed
calls = {'n': 0}
original = sw.execute_from


def crashing(*args, **kwargs):
    calls['n'] += 1
    if calls['n'] > 2:
        raise KeyboardInterrupt('simulated hard crash')
    return original(*args, **kwargs)


sw.execute_from = crashing
try:
    sw.run(r3['id'])
except KeyboardInterrupt:
    pass
sw.execute_from = original
d3 = sw.detail(r3['id'])
print('after crash', d3['status'], 'next', d3['next_index'],
      [(i['index'], i['status']) for i in d3['intervals']])
assert d3['intervals'][0]['status'] == 'published' and d3['intervals'][1]['status'] == 'published'
assert d3['intervals'][2]['status'] == 'pending'
before = [(i['index'], i['fingerprint']) for i in d3['intervals'] if i['status'] in ('published', 'merged')]
res = sw.resume(r3['id'])
sw.run(r3['id'])
d3 = sw.detail(r3['id'])
after = [(i['index'], i['fingerprint']) for i in d3['intervals'] if i['status'] in ('published', 'merged')]
print('resumed', d3['status'], 'complete', d3['coverage_complete'], 'confirmed', len(after))
assert all(after[i] == before[i] for i in range(len(before))), 'confirmed intervals must not be republished'
assert d3['status'] == 'completed' and d3['coverage_complete']
rerun = sw.resume(r3['id'])
assert rerun['status'] == 'completed' and Q.items[-1][1] == r3['id']
print('idempotent resume ok', flush=True)

print('== over-limit interval + resume ==', flush=True)
dup_sensors = [{'sensor_id': 1, 'zone': '北场', 'device_type': 'pump'} for _ in range(6)]
many = [{'sensor_id': 1, 'value': float(1 + i % 3), 'recorded_at': 'x'} for i in range(2000)]
with Session() as s:
    t3 = Trace(name='limit-trace', plan_id=1, dataset_id=1, status='completed',
               snapshot={'dataset': {'name': 'limit-ds', 'sensors': dup_sensors, 'readings': many},
                         'plan': {'steps': steps}})
    s.add(t3)
    s.commit()
    tid3 = t3.id
r4 = sw.create(SweepInput(trace_id=tid3, step_index=1, name='limit-sweep'))
sw.run(r4['id'])
d4 = sw.detail(r4['id'])
print('limit', d4['status'], [(i['index'], i['status'], i['threshold'], (i['error'] or '')[:16]) for i in d4['intervals']])
assert d4['status'] == 'failed'
failed = [i for i in d4['intervals'] if i['status'] == 'failed']
assert failed and all('10000' in (i['error'] or '') for i in failed)
published = [i for i in d4['intervals'] if i['status'] == 'published']
assert published, 'higher thresholds should still publish'
before4 = [(i['index'], i['fingerprint']) for i in d4['intervals'] if i['status'] == 'published']
sw.resume(r4['id'])
sw.run(r4['id'])
d4b = sw.detail(r4['id'])
after4 = [(i['index'], i['fingerprint']) for i in d4b['intervals'] if i['status'] == 'published']
print('after retry', d4b['status'], 'complete', d4b['coverage_complete'])
assert d4b['status'] == 'failed' and not d4b['coverage_complete']
assert after4 == before4, 'confirmed intervals must keep their fingerprints'
assert d4b['intervals'][0]['status'] == 'failed'
assert d4b['next_index'] == 4
print('limit + retry ok', flush=True)
print('ALL PASS')
