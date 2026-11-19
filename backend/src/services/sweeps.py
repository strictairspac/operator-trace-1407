from fastapi import HTTPException
import redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models.sweep import Sweep
from src.models.trace import Trace
from src.services.operators import execute_prefix,execute_from,sweep_partition
import hashlib,json
from sqlalchemy.orm.attributes import flag_modified

queue=redis.Redis.from_url(REDIS_URL)
QUEUE='operator-sweeps'
DONE=('published','merged')

def _fingerprint(result):
 """Identity of the complete final result: every output row plus its digest.

 Intermediate per-step row counts are deliberately excluded: two thresholds can
 differ in how many rows they scan/join yet produce the exact same grouping.
 """
 payload={'output':result['output'],'output_rows':result['output_rows'],'checksum':result['checksum']}
 return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def _validate_step(steps,step_index):
 if not isinstance(step_index,int) or isinstance(step_index,bool) or not 0<=step_index<len(steps):raise HTTPException(400,'阈值步骤不在计划中')
 step=steps[step_index]
 if step.get('op')!='filter' or step.get('compare') not in ('gte','lte') or step.get('field') not in ('sensor_id','value','count','sum','avg'):
  raise HTTPException(400,'请选择一道分组前或聚合后的数值范围筛选（gte/lte）')
 return step

def _partition(dataset,steps,step_index):
 rows,_,_=execute_prefix(dataset,steps,step_index)
 field=steps[step_index]['field']
 values=[row[field] for row in rows if field in row]
 try:return sweep_partition(values,steps[step_index]['compare'])
 except ValueError as exc:raise HTTPException(400,str(exc))

def _groups(intervals):
 """Group each published interval with adjacent merged intervals that share its result.

 Interval boundaries are never rewritten; a merged interval points at its group
 root. Merges can sit on either side of the root (a retried interval may match an
 already-published neighbour), so both directions are collected.
 """
 groups=[]
 for index,item in enumerate(intervals):
  if item['status']!='published':continue
  members=[index]
  while members[0]>0:
   left=intervals[members[0]-1]
   if left['status']=='merged' and left.get('merged_into')==index:members.insert(0,members[0]-1)
   else:break
  while members[-1]+1<len(intervals):
   right=intervals[members[-1]+1]
   if right['status']=='merged' and right.get('merged_into')==index:members.append(members[-1]+1)
   else:break
  first=intervals[members[0]];last=intervals[members[-1]]
  groups.append({'root_index':index,'lower':first['lower'],'upper':last['upper'],'lower_inclusive':first['lower_inclusive'],'upper_inclusive':last['upper_inclusive'],'member_indexes':members,'output_rows':item['output_rows'],'checksum':item['checksum'],'preview':item['preview'],'operators':item['operators']})
 return groups

def _summary(row):
 data=row.data or {};intervals=data.get('intervals',[])
 published=[i for i in intervals if i['status']=='published']
 merged=[i for i in intervals if i['status']=='merged']
 pending=[i for i in intervals if i['status']=='pending']
 failed=[i for i in intervals if i['status']=='failed']
 return {'id':row.id,'name':row.name,'trace_id':row.trace_id,'step_index':row.step_index,'status':row.status,'error':row.error,'created_at':row.created_at.isoformat() if row.created_at else None,'field':data.get('field'),'compare':data.get('compare'),'total_intervals':len(intervals),'published_count':len(published),'merged_count':len(merged),'pending_count':len(pending),'failed_count':len(failed),'next_index':data.get('next_index',0),'coverage_complete':bool(intervals) and all(i['status'] in DONE for i in intervals)}

def list_items():
 with Session() as s:return [_summary(r) for r in s.query(Sweep).order_by(Sweep.id.desc()).limit(100).all()]

def detail(item_id):
 with Session() as s:
  row=s.get(Sweep,item_id)
  if not row:raise HTTPException(404,'未找到阈值扫描')
  data=row.data or {};intervals=data.get('intervals',[])
  out=_summary(row);out['intervals']=intervals;out['groups']=_groups(intervals);out['steps']=data.get('steps');out['dataset_name']=data.get('dataset_name');out['trace_name']=data.get('trace_name')
  return out

def create(payload):
 with Session() as s:
  t=s.get(Trace,payload.trace_id)
  if not t or not t.snapshot:raise HTTPException(404,'未找到可复查的执行存档')
  steps=t.snapshot.get('plan',{}).get('steps') or []
  dataset=t.snapshot.get('dataset')
  if not dataset:raise HTTPException(400,'存档缺少输入快照')
  step=_validate_step(steps,payload.step_index)
  name=payload.name.strip() if isinstance(payload.name,str) and payload.name.strip() else f'{t.name} · {step["field"]} {step["compare"]} 阈值扫描'
  if s.query(Sweep).filter_by(name=name).first():raise HTTPException(409,'同名阈值扫描已存在，请更换名称')
  parts=_partition(dataset,steps,payload.step_index)
  intervals=[{**part,'index':i,'status':'pending','fingerprint':None,'output_rows':None,'checksum':None,'operators':None,'preview':None,'merged_into':None,'error':None} for i,part in enumerate(parts)]
  row=Sweep(name=name,trace_id=t.id,step_index=payload.step_index,status='queued',data={'dataset':dataset,'steps':steps,'dataset_name':t.snapshot.get('dataset',{}).get('name'),'trace_name':t.name,'field':step['field'],'compare':step['compare'],'intervals':intervals,'next_index':0})
  s.add(row);s.commit();s.refresh(row);result=_summary(row);result_id=row.id
 try:queue.rpush(QUEUE,result_id)
 except redis.RedisError:
  with Session() as s:r=s.get(Sweep,result_id);r.status='failed';r.error='队列不可用，请创建新任务';s.commit()
  raise HTTPException(503,'队列不可用，请稍后重试')
 return result

def resume(item_id):
 with Session() as s:
  row=s.get(Sweep,item_id)
  if not row:raise HTTPException(404,'未找到阈值扫描')
  if row.status=='completed':return _summary(row)
  data=row.data;intervals=data['intervals']
  for interval in intervals:
   if interval['status']=='failed':interval['status']='pending';interval['error']=None
  pending=[i for i,x in enumerate(intervals) if x['status'] not in DONE]
  data['next_index']=pending[0] if pending else len(intervals)
  row.data=data;flag_modified(row,'data');row.status='queued';row.error=None;s.commit();result=_summary(row)
 try:queue.rpush(QUEUE,item_id)
 except redis.RedisError:raise HTTPException(503,'队列不可用，请稍后重试')
 return result

def _root_of(intervals,index):
 item=intervals[index]
 if item['status']=='merged' and item.get('merged_into') is not None:return item['merged_into']
 return index

def _repoint(intervals,old_root,new_root):
 """Move every member of an already-published group under a new root (bounds untouched)."""
 if old_root==new_root:return
 for position,item in enumerate(intervals):
  if position==new_root:continue
  if position==old_root and item['status']=='published':
   item['status']='merged';item['merged_into']=new_root
  if item['status']=='merged' and item.get('merged_into')==old_root:item['merged_into']=new_root

def _compact(result):
 return {'output_rows':result['output_rows'],'checksum':result['checksum'],'preview':result['output'][:5],'operators':[{'op':o['op'],'input_rows':o['input_rows'],'output_rows':o['output_rows'],'checksum':o['checksum']} for o in result['operators']]}

def run(sweep_id):
 """Resume from the stored cursor; the shared prefix runs once and each interval commits atomically."""
 with Session() as s:
  row=s.get(Sweep,sweep_id)
  if not row or row.status not in ('queued','running'):return
  if row.status=='queued':row.status='running';s.commit()
  data=row.data
 dataset=data['dataset'];steps=data['steps'];step_index=row.step_index
 rows,reads,prefix_trace=execute_prefix(dataset,steps,step_index)
 suffix=[dict(steps[step_index]),*steps[step_index+1:]]
 try:
  while True:
   with Session() as s:
    row=s.get(Sweep,sweep_id)
    if not row:return
    data=row.data;intervals=data['intervals'];i=data.get('next_index',0)
    if i>=len(intervals):
     failed=any(x['status']=='failed' for x in intervals)
     row.status='failed' if failed else 'completed'
     row.error='部分区间超出执行限制，可续跑重试失败区间' if failed else None
     s.commit();return
    if intervals[i]['status'] in (*DONE,'failed'):
     data['next_index']=i+1;row.data=data;flag_modified(row,'data');s.commit();continue
    interval=intervals[i]
   threshold_step=dict(suffix[0]);threshold_step['value']=interval['threshold']
   error=None
   try:
    result=execute_from(dataset,[threshold_step,*suffix[1:]],list(rows),reads,prefix_trace)
    compact=_compact(result);stamp=_fingerprint(result)
   except Exception as exc:
    compact=None;stamp=None;error=str(exc)[:500]
   with Session() as s:
    row=s.get(Sweep,sweep_id)
    if not row:return
    data=row.data;intervals=data['intervals'];current=intervals[i]
    if current['status'] not in (*DONE,'failed'):
     if error:
      current['status']='failed';current['error']=error
     else:
      previous=intervals[i-1] if i>0 else None
      following=intervals[i+1] if i+1<len(intervals) else None
      left=previous is not None and previous['status'] in DONE and previous.get('fingerprint')==stamp
      right=following is not None and following['status'] in DONE and following.get('fingerprint')==stamp
      if left or right:
       # join the adjacent group(s); a match on both sides bridges them into one
       root=_root_of(intervals,i-1) if left else _root_of(intervals,i+1)
       if left and right:_repoint(intervals,_root_of(intervals,i+1),root)
       current['status']='merged';current['merged_into']=root;current['fingerprint']=stamp
       current.update({k:compact[k] for k in ('output_rows','checksum','preview','operators')})
      else:
       current['status']='published';current['fingerprint']=stamp
       current.update(compact)
    data['next_index']=i+1;row.data=data;flag_modified(row,'data');s.commit()
 except Exception as exc:
  with Session() as s:
   row=s.get(Sweep,sweep_id)
   if row:row.status='failed';row.error=str(exc)[:1000];s.commit()
