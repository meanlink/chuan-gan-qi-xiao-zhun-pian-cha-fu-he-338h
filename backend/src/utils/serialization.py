import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at}
def job_dict(j, run=None, shared=1):
    d={k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_by','created_at','finished_at','withdrawn']}
    d['run_id']=j.run_id
    d['shared']=shared  # 合用本次计算的未撤销申请数
    d['recoveries']=run.recoveries if run else 0  # 中断恢复次数，>0 表示结果历经恢复
    d['attempts']=run.attempts if run else 0
    return d
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
