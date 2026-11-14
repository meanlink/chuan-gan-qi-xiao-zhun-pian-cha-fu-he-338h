import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from src.config.database import get_db
from src.models import Job, Run, Dataset
from src.schemas.job import JobInput
from src.middlewares.auth import current_user, can_write, admin_only
from src.services import jobs
from src.services import runs as run_service
from src.services.audit import record
from src.utils.serialization import job_dict
router=APIRouter(prefix='/jobs')
def with_run(db,j):
    run=db.get(Run,j.run_id) if j.run_id else None
    return job_dict(j,run,run_service.active_count(db,run.id) if run else 1)
@router.get('')
def listing(db=Depends(get_db),u=Depends(current_user)):
    items=list(db.scalars(select(Job).order_by(Job.id.desc()).limit(100)))
    runs={r.id:r for r in db.scalars(select(Run).where(Run.id.in_({j.run_id for j in items if j.run_id})))}
    counts=dict(db.execute(select(Job.run_id,func.count()).where(Job.run_id.in_(runs.keys()),Job.withdrawn==False).group_by(Job.run_id)).all()) if runs else {}
    return [job_dict(j,runs.get(j.run_id),counts.get(j.run_id,1)) for j in items]
@router.post('',status_code=201)
def create(data:JobInput,db=Depends(get_db),u=Depends(can_write)):
    j,run=jobs.create(db,data,u)
    record(db,u.email,'job.create',{'id':j.id,'run':run.id,'params':j.params,'reused':run.status=='completed','shared':run_service.active_count(db,run.id)})
    db.commit()
    if run.status=='queued': jobs.enqueue(run.id)
    run_service.reconcile(db,j)  # 与并发发布擦肩时对齐到最新计算状态
    return with_run(db,j)
@router.get('/{id}')
def detail(id:int,db=Depends(get_db),u=Depends(current_user)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    return with_run(db,j)
@router.post('/{id}/approve')
def approve(id:int,db=Depends(get_db),u=Depends(admin_only)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.status!='completed':raise HTTPException(409,'仅已完成结果可以批准')
    j.approved=True; record(db,u.email,'job.approve',{'id':id}); db.commit()
    return with_run(db,j)
@router.post('/{id}/withdraw')
def withdraw(id:int,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if u.role!='admin' and j.created_by!=u.id: raise HTTPException(403,'只能撤销本人提交的申请')
    if j.withdrawn: raise HTTPException(409,'该申请已撤销')
    if j.status not in ('waiting','running'): raise HTTPException(409,'仅等待共享计算或运行中的申请可以撤销')
    run=db.get(Run,j.run_id) if j.run_id else None
    if run:
        db.refresh(run)  # 以计算的最新状态为准，避免与并发发布擦肩
        if run.status not in ('queued','running'): raise HTTPException(409,'共享计算已结束，申请不可撤销')
    j.withdrawn=True; j.withdrawn_at=time.time(); j.status='withdrawn'
    record(db,u.email,'job.withdraw',{'id':j.id,'run':j.run_id})
    if run:
        run_service.stop_if_orphaned(db,run,u.email)  # 全部撤销后停止计算且不发布
    db.commit()
    return with_run(db,j)
@router.post('/{id}/retry')
def retry(id:int,db=Depends(get_db),u=Depends(can_write)):
    j=db.get(Job,id)
    if not j: raise HTTPException(404,'分析任务不存在')
    if j.withdrawn: raise HTTPException(409,'已撤销的申请不能重试')
    if j.status!='failed': raise HTTPException(409,'仅失败的申请可以重试')
    run=db.get(Run,j.run_id) if j.run_id else None
    if run is None:  # 共享计算上线前的历史申请：补挂到对应指纹的计算
        dataset=db.get(Dataset,j.dataset_id)
        if not dataset: raise HTTPException(404,'数据批次不存在')
        run=run_service.get_or_create(db,dataset,j.params)
        run_service.attach(j,run)
    if run.status in ('failed','stopped'):
        run_service.revive(db,run)  # 重试不重复创建申请，原计算重新排队
    else:
        run_service.sync_jobs(db,run)  # 其他申请已触发重试或结果已完成，直接对齐状态
    record(db,u.email,'job.retry',{'id':j.id,'run':run.id})
    db.commit()
    if run.status=='queued': jobs.enqueue(run.id)
    run_service.reconcile(db,j)
    return with_run(db,j)
