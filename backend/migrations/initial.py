from sqlalchemy import inspect, text, select
from src.config.database import Base, engine, Session
from src import models
def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        cols={c['name'] for c in inspect(conn).get_columns('jobs')}
        # 旧库增量列：共享计算挂接与撤销标记（新库由 create_all 一并建好）。
        for name, ddl in [('run_id','ALTER TABLE jobs ADD COLUMN run_id INTEGER'),
                          ('withdrawn','ALTER TABLE jobs ADD COLUMN withdrawn BOOLEAN DEFAULT FALSE'),
                          ('withdrawn_at','ALTER TABLE jobs ADD COLUMN withdrawn_at DOUBLE PRECISION')]:
            if name not in cols: conn.execute(text(ddl))
        conn.execute(text("UPDATE jobs SET status='waiting' WHERE status='queued'"))
    attach_legacy_active_jobs()
def attach_legacy_active_jobs():
    """共享计算上线前遗留的等待/运行中申请：补建共享计算并挂接，结果列保持自含。"""
    from src.models import Job, Dataset
    from src.services import runs as run_service
    with Session() as db:
        legacy=list(db.scalars(select(Job).where(Job.run_id==None, Job.status.in_(['waiting','running']))))
        for j in legacy:
            dataset=db.get(Dataset,j.dataset_id)
            if not dataset:
                j.status='failed'; j.error='数据批次不存在，无法恢复计算'; continue
            run=run_service.get_or_create(db,dataset,j.params)
            if run.status in ('failed','stopped'): run_service.revive(db,run)
            run_service.attach(j,run)
        if legacy: db.commit()
if __name__=='__main__':migrate()
