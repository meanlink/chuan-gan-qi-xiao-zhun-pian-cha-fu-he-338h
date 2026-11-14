import os, time, json, logging, socket, threading
from pathlib import Path
from sqlalchemy import select
from redis import Redis
from src.config.database import Session
from src.config.settings import REDIS_URL
from src.models import Run, Dataset, Report
from src.services.business import analyze
from src.services.reports import deliver
from src.services.audit import record
from src.services import runs as run_service
logging.basicConfig(level=logging.INFO)
WORKER_ID=f'{socket.gethostname()}:{os.getpid()}'
def execute(run_id):
    with Session() as db:
        epoch=run_service.claim(db,run_id,WORKER_ID)
        if epoch is None:return  # 已被其他进程认领
        run=db.get(Run,run_id)
        dataset=db.get(Dataset,run.dataset_id)
        if not dataset:
            run_service.publish(run_id,epoch,WORKER_ID,error='数据批次不存在')
            return
        records,params=dataset.records,dict(run.params)
    stop=threading.Event()
    beat=threading.Thread(target=run_service.heartbeat_loop,args=(run_id,epoch,WORKER_ID,stop),daemon=True)
    beat.start()
    try:
        result=analyze(records,params)
        json.dumps(result,allow_nan=False)
        run_service.publish(run_id,epoch,WORKER_ID,result=result)
    except Exception as e:
        logging.exception('Analysis failed')
        run_service.publish(run_id,epoch,WORKER_ID,error=e)
    finally:
        stop.set();beat.join(timeout=3)
def tick():
    with Session() as db:
        run_service.recover_stale(db)  # 中断的计算重新排队，等待认领
        queued=list(db.scalars(select(Run.id).where(Run.status=='queued').order_by(Run.id).limit(3)))
    for run_id in queued:execute(run_id)
    with Session() as db:
        for r in db.scalars(select(Report).where(Report.enabled==True,Report.next_run<=time.time())):
            d=deliver(db,r)
            if d:record(db,'worker','report.delivered',{'id':r.id,'delivery':d.id})
        db.commit()
def main():
    r=Redis.from_url(REDIS_URL,socket_timeout=3)
    # 进程重启后先接管中断的计算；多进程并发接管由条件更新与 epoch 栅栏保证安全。
    with Session() as db:
        run_service.recover_stale(db)
    while True:
        Path('/tmp/heartbeat').touch()
        try:
            item=r.blpop('analysis:queue',timeout=1)
            if item:execute(int(item[1]))
        except Exception:
            logging.exception('Worker retry');time.sleep(2)
        try:
            tick()  # SQL 排队状态兜底：Redis 不可用时仍按库内状态执行与恢复
        except Exception:
            logging.exception('Tick failed');time.sleep(2)
if __name__=='__main__':main()
