from enum import Enum
class Role(str, Enum):
    admin = 'admin'
    analyst = 'analyst'
    viewer = 'viewer'
class JobStatus(str, Enum):
    waiting = 'waiting'      # 等待共享计算
    running = 'running'      # 运行中
    completed = 'completed'  # 已完成
    failed = 'failed'        # 计算失败
    withdrawn = 'withdrawn'  # 已撤销
class RunStatus(str, Enum):
    queued = 'queued'        # 排队等待认领
    running = 'running'      # 执行中
    completed = 'completed'  # 已完成，结果可复用
    failed = 'failed'        # 失败，可重试
    stopped = 'stopped'      # 全部申请撤销后停止，不发布
