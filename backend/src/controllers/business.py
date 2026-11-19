from src.services import datasets,plans,traces,sweeps
from src.services.audit import log
def save_dataset(data,user,item_id=None):
 row=datasets.save(data,item_id);log(user.email,'dataset.save',row['name']);return row
def save_plan(data,user,item_id=None):
 row=plans.save(data,item_id);log(user.email,'plan.save',row['name']);return row
def start_trace(data,user):
 row=traces.create(data);log(user.email,'trace.queue',row['name']);return row

def start_sweep(data,user):
 row=sweeps.create(data);log(user.email,'sweep.queue',row['name']);return row
def resume_sweep(item_id,user):
 row=sweeps.resume(item_id);log(user.email,'sweep.resume',row['name']);return row
