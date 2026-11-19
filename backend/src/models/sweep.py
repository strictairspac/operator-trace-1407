from sqlalchemy import Column,Integer,String,JSON,DateTime,func,ForeignKey
from src.config.database import Base
class Sweep(Base):
 """A threshold sweep over one filter step of an immutable trace snapshot."""
 __tablename__='sweeps'
 id=Column(Integer,primary_key=True)
 name=Column(String(160),unique=True,nullable=False)
 trace_id=Column(Integer,ForeignKey('traces.id'),nullable=False)
 step_index=Column(Integer,nullable=False)
 status=Column(String(20),default='queued',nullable=False)
 data=Column(JSON,nullable=False)
 error=Column(String(1000),nullable=True)
 created_at=Column(DateTime,server_default=func.now())
