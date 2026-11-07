from datetime import datetime, timezone
from sqlalchemy import create_engine, ForeignKey, String, Text, JSON, DateTime, Integer, Boolean, event, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(600))
    kind: Mapped[str] = mapped_column(String(20), index=True)
    url: Mapped[str] = mapped_column(String(512), unique=True)
    source: Mapped[str] = mapped_column(Text, default='Добавлено пользователем')
    reference: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule_hours: Mapped[int] = mapped_column(Integer, default=0)
    next_run: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fact_sources: Mapped[list] = mapped_column(JSON, default=list)

class Run(Base):
    __tablename__ = 'runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey('organizations.id'), index=True)
    organization: Mapped[Organization] = relationship()
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default='')
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    results: Mapped[list['Result']] = relationship(cascade='all, delete-orphan', order_by='Result.id')
    pages: Mapped[list['Page']] = relationship(cascade='all, delete-orphan', order_by='Page.id')

class Page(Base):
    __tablename__ = 'pages'
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id'), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default='')
    status_code: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(40), default='other')
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    text: Mapped[str] = mapped_column(Text, default='')
    digest: Mapped[str] = mapped_column(String(64), default='')
    details: Mapped[dict] = mapped_column(JSON, default=dict)

class Result(Base):
    __tablename__ = 'results'
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('runs.id'), index=True)
    rule: Mapped[str] = mapped_column(String(100))
    section: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20))
    priority: Mapped[str] = mapped_column(String(20), default='medium')
    title: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text, default='')
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    review: Mapped[str] = mapped_column(String(20), default='unreviewed')
    review_note: Mapped[str] = mapped_column(Text, default='')

Index('uq_active_run_per_org',Run.org_id,unique=True,sqlite_where=Run.status.in_(['queued','running']))

def connect(url=None):
    from .config import database_url
    engine = create_engine(url or database_url(), pool_pre_ping=True,
                           connect_args={'check_same_thread':False,'timeout':30})
    @event.listens_for(engine,'connect')
    def configure_sqlite(connection,record):
        cursor=connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()
    return engine, sessionmaker(engine, expire_on_commit=False)

def init_database(engine):
    with engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA journal_mode=WAL')
    Base.metadata.create_all(engine)
