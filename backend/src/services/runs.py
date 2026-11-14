"""共享计算 Run 的生命周期：认领、心跳、栅栏发布、中断恢复、停止与状态同步。

并发安全约定：
- 认领、发布、恢复全部使用带条件的原子 UPDATE，多进程同时接管时只有一个胜出。
- 每次认领递增 epoch（栅栏令牌）。旧执行进程即使晚完成，其发布因 epoch/status
  不再匹配而影响 0 行，结果直接丢弃，不得覆盖新执行的结果。
"""
import time
import logging
from sqlalchemy import select, update, func, or_
from sqlalchemy.exc import IntegrityError
from src.config.database import Session
from src.models import Run, Job
from src.services.audit import record
from src.utils.serialization import checksum

STALE_SECONDS = 10       # 心跳超过该时长视为执行进程已中断
HEARTBEAT_INTERVAL = 2   # 执行中心跳间隔


def fingerprint(dataset_checksum, params):
    """同批样本（内容指纹）+ 相同参数 → 同一个共享计算。"""
    return checksum({'dataset': dataset_checksum, 'params': params})


def get_or_create(db, dataset, params):
    """按指纹取共享计算；不存在则创建。唯一约束兜底并发同时创建。"""
    fp = fingerprint(dataset.checksum, params)
    run = db.scalar(select(Run).where(Run.fingerprint == fp))
    if run:
        return run
    run = Run(fingerprint=fp, dataset_id=dataset.id, params=params, status='queued', created_at=time.time())
    db.add(run)
    try:
        with db.begin_nested():
            db.flush()
        return run
    except IntegrityError:
        # 另一请求并发创建了同一指纹的计算：丢弃保存点回滚后的游离对象，取已提交记录合用。
        db.expunge(run)
        return db.scalar(select(Run).where(Run.fingerprint == fp))


def attach(job, run):
    """把申请挂接到共享计算，并按计算当前状态初始化申请快照。"""
    job.run_id = run.id
    if run.status == 'completed':  # 已完成结果直接复用
        job.status, job.result, job.error, job.finished_at = 'completed', run.result, '', run.finished_at
    elif run.status == 'running':
        job.status = 'running'
    else:
        job.status, job.error = 'waiting', ''


def revive(db, run):
    """失败/已停止的计算重新排队（重试不新建计算，更不新建申请）。"""
    res = db.execute(update(Run).where(Run.id == run.id, Run.status.in_(['failed', 'stopped']))
                     .values(status='queued', error='', result={}, epoch=Run.epoch + 1,
                             heartbeat_at=None, worker_id='', finished_at=None))
    db.refresh(run)  # 并发下他人可能已抢先重排，读取最新状态
    if res.rowcount:
        sync_jobs(db, run)
    return run


def sync_jobs(db, run):
    """把共享计算状态同步到各未撤销申请（各自仍保留名称/批准/分发）。"""
    mapping = {
        'queued':    {'status': 'waiting', 'error': '', 'finished_at': None},
        'running':   {'status': 'running'},
        'completed': {'status': 'completed', 'result': run.result, 'error': '', 'finished_at': run.finished_at},
        'failed':    {'status': 'failed', 'error': run.error, 'finished_at': run.finished_at},
    }
    values = mapping.get(run.status)
    if values:
        db.execute(update(Job).where(Job.run_id == run.id, Job.withdrawn == False).values(**values))


def active_count(db, run_id):
    """仍挂在该计算上的未撤销申请数。"""
    return db.scalar(select(func.count()).select_from(Job).where(Job.run_id == run_id, Job.withdrawn == False)) or 0


def reconcile(db, job):
    """申请提交后与计算状态对齐一次。

    挂接时读到的 run 状态可能是并发发布前的快照（申请 INSERT 与 publish 的
    同步擦肩而过）。提交后重读最新计算状态并补同步；此后的发布会覆盖到已提交的申请。
    """
    if not job.run_id or job.withdrawn:
        return
    run = db.get(Run, job.run_id)
    if not run:
        return
    db.refresh(run)
    sync_jobs(db, run)
    db.commit()
    db.refresh(job)


def stop_if_orphaned(db, run, actor):
    """全部申请撤销后停止计算且不发布：运行中的执行发布时会被栅栏挡下。"""
    if active_count(db, run.id) == 0 and run.status in ('queued', 'running'):
        res = db.execute(update(Run).where(Run.id == run.id, Run.status.in_(['queued', 'running']))
                         .values(status='stopped', finished_at=time.time(), heartbeat_at=None))
        db.refresh(run)
        if res.rowcount:
            record(db, actor, 'run.stopped', {'id': run.id})
            return True
    return False


def claim(db, run_id, worker_id):
    """原子认领排队中的计算；返回本轮 epoch，被他人抢先则返回 None。"""
    res = db.execute(update(Run).where(Run.id == run_id, Run.status == 'queued')
                     .values(status='running', epoch=Run.epoch + 1, attempts=Run.attempts + 1,
                             worker_id=worker_id, heartbeat_at=time.time()))
    if not res.rowcount:
        db.rollback()
        return None
    run = db.get(Run, run_id)
    db.refresh(run)
    sync_jobs(db, run)
    db.commit()
    return run.epoch


def heartbeat_loop(run_id, epoch, worker_id, stop):
    """执行期间按 epoch 续心跳；失去栅栏（被接管/被停止）后心跳自然失效。"""
    while not stop.wait(HEARTBEAT_INTERVAL):
        try:
            with Session() as db:
                db.execute(update(Run).where(Run.id == run_id, Run.status == 'running',
                                             Run.epoch == epoch, Run.worker_id == worker_id)
                           .values(heartbeat_at=time.time()))
                db.commit()
        except Exception:
            logging.exception('Run heartbeat failed')


def publish(run_id, epoch, worker_id, result=None, error=None):
    """栅栏发布：仅当仍是 (running, 同 epoch, 同执行者) 时写入，否则丢弃。

    旧执行进程晚完成时影响 0 行 → 返回 False，绝不覆盖新执行的结果。
    """
    with Session() as db:
        now = time.time()
        if error is None:
            values = {'status': 'completed', 'result': result, 'error': '', 'finished_at': now, 'heartbeat_at': None}
        else:
            values = {'status': 'failed', 'error': str(error)[:990], 'finished_at': now, 'heartbeat_at': None}
        res = db.execute(update(Run).where(Run.id == run_id, Run.status == 'running',
                                           Run.epoch == epoch, Run.worker_id == worker_id)
                         .values(**values))
        if not res.rowcount:
            db.rollback()
            record(db, 'worker', 'run.fenced', {'id': run_id, 'epoch': epoch, 'worker': worker_id})
            db.commit()
            logging.warning('Stale executor fenced for run %s epoch %s', run_id, epoch)
            return False
        run = db.get(Run, run_id)
        db.refresh(run)
        sync_jobs(db, run)
        record(db, 'worker', 'run.' + run.status, {'id': run.id, 'epoch': epoch, 'attempts': run.attempts, 'recoveries': run.recoveries})
        db.commit()
        return True


def recover_stale(db, now=None):
    """把心跳过期的运行中计算重新排队（中断恢复）；每次接管递增 recoveries。"""
    now = now or time.time()
    ids = list(db.scalars(select(Run.id).where(Run.status == 'running',
                                               or_(Run.heartbeat_at == None, Run.heartbeat_at < now - STALE_SECONDS))))
    recovered = []
    for run_id in ids:
        res = db.execute(update(Run).where(Run.id == run_id, Run.status == 'running')
                         .values(status='queued', recoveries=Run.recoveries + 1, worker_id='', heartbeat_at=None))
        if res.rowcount:  # 并发接管时只有一个进程能恢复同一次计算
            run = db.get(Run, run_id)
            db.refresh(run)
            sync_jobs(db, run)
            record(db, 'worker', 'run.recovered', {'id': run.id, 'recoveries': run.recoveries})
            recovered.append(run_id)
    if recovered:
        db.commit()
    return recovered
