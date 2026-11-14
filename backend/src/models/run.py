from sqlalchemy import String, JSON, Double, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from src.config.database import Base
class Run(Base):
    """一次共享计算。同批样本指纹 + 相同参数只存在一个 Run，各复核申请（Job）挂接其上。"""
    __tablename__ = 'runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey('datasets.id'))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default='queued')  # queued/running/completed/failed/stopped
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(String(1000), default='')
    epoch: Mapped[int] = mapped_column(Integer, default=0)  # 栅栏令牌：每次认领递增，旧执行晚完成不得覆盖
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    recoveries: Mapped[int] = mapped_column(Integer, default=0)  # 中断后被接管的次数
    worker_id: Mapped[str] = mapped_column(String(120), default='')
    heartbeat_at: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[float] = mapped_column(Double)
    finished_at: Mapped[float | None] = mapped_column(Double, nullable=True)
