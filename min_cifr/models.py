from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class OrgType(str, Enum):
    SCHOOL = "school"
    KINDERGARTEN = "kindergarten"


class Severity(str, Enum):
    HIGH = "высокая"
    MEDIUM = "средняя"
    LOW = "низкая"


class Status(str, Enum):
    FAIL = "нарушение"
    WARN = "риск"
    OK = "ок"
    NA = "недостаточно данных"


@dataclass(frozen=True)
class Org:
    name: str
    domain: str
    kind: OrgType

    @property
    def url(self) -> str:
        return f"https://{self.domain}/"


@dataclass
class NewsItem:
    title: str
    published: Optional[date]
    url: str
    text: str = ""
    event_date: Optional[date] = None


@dataclass
class EventItem:
    title: str
    start: Optional[date]
    end: Optional[date]
    url: str = ""
    dated: bool = True


@dataclass
class Person:
    name: str
    role: str = ""
    has_photo: bool = False
    has_education: bool = False
    has_contacts: bool = False


@dataclass
class SectionData:
    name: str
    url: str = ""
    found: bool = False
    filled: bool = False
    has_stub: bool = False
    text: str = ""


@dataclass
class SiteData:
    org: Org
    fetched_at: datetime = field(default_factory=datetime.now)
    home_text: str = ""
    news: list[NewsItem] = field(default_factory=list)
    events: list[EventItem] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    sections: dict[str, SectionData] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class Finding:
    check_id: str
    section: str
    problem: str
    severity: Severity
    recommendation: str
    evidence: str = ""
    status: Status = Status.FAIL


@dataclass
class SiteReport:
    org: Org
    score: float
    findings: list[Finding] = field(default_factory=list)
    is_reference: bool = False
    checked_at: datetime = field(default_factory=datetime.now)

    def count(self, sev: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == sev and f.status == Status.FAIL)
