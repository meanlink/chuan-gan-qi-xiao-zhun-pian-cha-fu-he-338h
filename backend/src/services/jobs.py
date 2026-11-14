import time
from fastapi import HTTPException
from redis import Redis
from src.config.settings import REDIS_URL
from src.models import Dataset, Job
from src.services.business import metadata
from src.services import runs as run_service
def normalize_params(raw):
    allowed={p['key']:p for p in metadata().get('parameters',[])}
    if set(raw)-set(allowed): raise HTTPException(422,'包含未知分析参数')
    params={k:p['default'] for k,p in allowed.items()}
    params.update(raw)
    for key,p in allowed.items():
        v=params[key]
        if p['type']=='number':
            try:
                v=float(v)
                if not (p.get('min',-1e9)<=v<=p.get('max',1e9)): raise ValueError()
                params[key]=v
            except (ValueError,TypeError): raise HTTPException(422, f'{p["label"]} 超出范围或非数值')
        elif str(v) not in [str(o['value']) for o in p.get('options',[])]:
            raise HTTPException(422,f'{p["label"]} 不是有效选项')
    return params
def create(db, data, user):
    """新建复核申请。同批样本 + 相同参数合用一次共享计算，申请各自保留名称/批准/分发。"""
    dataset=db.get(Dataset,data.dataset_id)
    if not dataset: raise HTTPException(404,'数据批次不存在')
    params=normalize_params(data.params)
    run=run_service.get_or_create(db,dataset,params)
    if run.status in ('failed','stopped'):
        run_service.revive(db,run)  # 失败/已停止的共享计算随新申请重新排队
    j=Job(name=data.name, dataset_id=dataset.id, params=params, created_by=user.id, created_at=time.time())
    run_service.attach(j,run)  # 已完成结果直接复用，等待/运行中则共享本次计算
    db.add(j); db.flush()
    return j, run
def enqueue(run_id):
    try:
        r=Redis.from_url(REDIS_URL); r.rpush('analysis:queue',run_id); r.close()
    except Exception:
        pass # SQL queued status is the durable fallback
