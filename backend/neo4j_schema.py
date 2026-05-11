"""
Legal GraphRAG — Neo4j Schema
===========================
Law Domain + Case Domain + Common Entities

Labels:
  Law Entity Types (สีเขียว): Law, Section, Clause, Penalty, Right, Duty, Authority, Subject, Amendment, LegalReference
  Case Entity Types (สีส้ม): Case, Fact, Person, Evidence, LegalIssue, ApplicableLaw, Court, Judge
  Common Entity Types (สีเทา): Person, Organization, Location, Event, Document
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class AccessLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    REGULATED = "REGULATED"
    CONFIDENTIAL = "CONFIDENTIAL"
    CLASSIFIED = "CLASSIFIED"


class LawType(str, Enum):
    CONSTITUTION = "CONSTITUTION"           # รัฐธรรมนูญ
    ACT = "ACT"                              # พระราชบัญญัติ
    ROYAL_DECREE = "ROYAL_DECREE"            # พระราชกำหนด
    EMERGENCY_DECREE = "EMERGENCY_DECREE"    # พระราชกำหนดฉุกเฉิน
    CODE = "CODE"                            # ประมวลกฎหมาย
    MINISTERIAL_REGULATION = "MINISTERIAL_REGULATION"  # กฎกระทรวง
    ROYAL_ORDER = "ROYAL_ORDER"              # พระราชโองการ
    CABINET_RESOLUTION = "CABINET_RESOLUTION"  # มติคณะรัฐมนตรี
    ORDER = "ORDER"                          # คำสั่ง
    NOTIFICATION = "NOTIFICATION"             # ประกาศ/กรม/กอง
    GENERAL = "GENERAL"                      # ทั่วไป


class CaseType(str, Enum):
    CRIMINAL = "CRIMINAL"
    CIVIL = "CIVIL"
    ADMINISTRATIVE = "ADMINISTRATIVE"
    CONSTITUTIONAL = "CONSTITUTIONAL"
    LABOR = "LABOR"
    TAX = "TAX"
    INTELLECTUAL_PROPERTY = "INTELLECTUAL_PROPERTY"
    OTHER = "OTHER"


class PersonRole(str, Enum):
    DEFENDANT = "DEFENDANT"        # จำเลย
    PLAINTIFF = "PLAINTIFF"        # โจทก์
    ACCUSED = "ACCUSED"            # ผู้ถูกกล่าวหา
    SUSPECT = "SUSPECT"            # ผู้ต้องหา
    VICTIM = "VICTIM"              # ผู้เสียหาย
    WITNESS = "WITNESS"            # พยาน
    JUDGE = "JUDGE"                # ผู้พิพากษา
    PROSECUTOR = "PROSECUTOR"      # อัยการ
    LAWYER = "LAWYER"             # ทนาย
    EXPERT = "EXPERT"              # ผู้เชี่ยวชาญ
    OFFICER = "OFFICER"            # เจ้าหน้าที่
    OTHER = "OTHER"


# ─── Law Domain Entities ────────────────────────────────────────────────────

class Law(BaseModel):
    """กฎหมายฉบับหนึ่ง (พ.ร.บ., พ.ร.ก., ประมวล, ฯลฯ)"""
    law_id: str = Field(description="เลขที่ของกฎหมาย mis_xxxx_xxxx")
    title: str = Field(description="ชื่อกฎหมาย")
    law_type: LawType
    effective_date: Optional[str] = Field(default=None, description="วันที่มีผลบังคับใช้")
    expiration_date: Optional[str] = None
    issued_by: Optional[str] = Field(default=None, description="ผู้ลงนาม/ออกคำสั่ง")
    agency_responsible: Optional[str] = Field(default=None, description="หน่วยงานรับผิดชอบหลัก")
    gazette_date: Optional[str] = Field(default=None, description="วันที่ลงประกาศราชกิจจา")
    access_level: AccessLevel = AccessLevel.PUBLIC
    parent_law_id: Optional[str] = Field(default=None, description="กฎหมายแม่ (ถ้าเป็นกฎหมายลูก)")
    related_laws: list[str] = Field(default_factory=list, description="กฎหมายที่เกี่ยวข้อง")
    raw_text_summary: Optional[str] = None
    source_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Section(BaseModel):
    """มาตราในกฎหมาย"""
    section_id: str = Field(description="เช่น 'ม.45' หรือ 'ข้อ 45'")
    law_id: str
    section_number: str = Field(description="เช่น '45', '45/1', '45/2'")
    title: Optional[str] = Field(default=None, description="หัวข้อมาตรา (ถ้ามี)")
    content: str = Field(description="เนื้อหามาตราแบบ plain text")
    access_level: AccessLevel = AccessLevel.PUBLIC
    subject_type: Optional[str] = Field(default=None, description="ประเภทผู้รับสภาพ mis_xxx")
    chapter: Optional[str] = None
    part: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Clause(BaseModel):
    """ข้อย่อยในมาตรา (ถ้ามีการแบ่งข้อย่อย)"""
    clause_id: str
    section_id: str
    clause_number: str
    content: str
    order_index: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Penalty(BaseModel):
    """บทลงโทษ"""
    penalty_id: str
    section_id: str  # มาตราที่กำหนดโทษ
    offense_description: str = Field(description="ความผิดที่ระบุ")
    penalty_type: str = Field(description="จำคุก/ปรับ/อาญาจำคุก/จำเลย/ริบทรัพย์/อื่นๆ")
    penalty_value: Optional[str] = Field(default=None, description="ขนาดโทษ เช่น 'ไม่เกิน 5 ปี', 'ไม่เกิน 100,000 บาท'")
    imprisonment_range: Optional[str] = None
    fine_range: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Right(BaseModel):
    """สิทธิที่กฎหมายให้แก่บุคคล"""
    right_id: str
    section_id: str
    right_name: str = Field(description="ชื่อสิทธิ")
    description: str = Field(description="รายละเอียดสิทธิ")
    beneficiary: Optional[str] = Field(default=None, description="ผู้ได้รับสิทธิ")
    conditions: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Duty(BaseModel):
    """หน้าที่ที่กฎหมายกำหนด"""
    duty_id: str
    section_id: str
    duty_name: str
    description: str
    obligated_parties: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Authority(BaseModel):
    """อำนาจหน้าที่ของเจ้าหน้าที่"""
    authority_id: str
    section_id: str
    authority_name: str
    description: str
    officer_type: Optional[str] = Field(default=None, description="ประเภทเจ้าหน้าที่ mis_xxx")
    scope: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Subject(BaseModel):
    """ผู้รับสภาพของกฎหมาย (ใครต้องปฏิบัติตาม)"""
    subject_id: str
    law_id: str
    subject_type: str = Field(description="ประเภทผู้รับ เช่น 'บุคคลทั่วไป', 'ข้าราชการ', 'นิติบุคคล'")
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Amendment(BaseModel):
    """การแก้ไขเพิ่มเติมกฎหมาย"""
    amendment_id: str
    amended_law_id: str
    amending_law_id: str
    amendment_date: str
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LegalReference(BaseModel):
    """การอ้างอิงกฎหมาย (cite/cross-reference)"""
    source_section_id: str
    target_law_id: Optional[str] = None
    target_section_id: Optional[str] = None
    reference_type: str = Field(description="amends/cites/repeals/supersedes")
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Case Domain Entities (ออกแบบไว้ก่อน — ยังไม่ implement ตอนนี้) ──────────

class Case(BaseModel):
    """สำนวนคดี"""
    case_id: str
    case_number: str = Field(description="หมายเลขคดี")
    case_type: CaseType
    court: Optional[str] = None
    filing_date: Optional[str] = None
    status: Optional[str] = None
    access_level: AccessLevel = AccessLevel.CONFIDENTIAL
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Fact(BaseModel):
    """ข้อเท็จจริงในคดี"""
    fact_id: str
    case_id: str
    fact_description: str
    actor: Optional[str] = None
    action: Optional[str] = None
    object_: Optional[str] = Field(default=None, alias="object")
    method: Optional[str] = None
    result: Optional[str] = None
    location: Optional[str] = None
    event_time: Optional[str] = None
    sequence_order: int
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CasePerson(BaseModel):
    """บุคคลในคดี"""
    person_id: str
    case_id: str
    full_name: Optional[str] = None
    role: PersonRole
    role_description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class LegalIssue(BaseModel):
    """ประเด็นกฎหมายที่ต้องวินิจฉัย"""
    issue_id: str
    case_id: str
    issue_description: str
    issue_type: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ApplicableLaw(BaseModel):
    """มาตราที่เข้าข่ายกับข้อเท็จจริง"""
    applicable_law_id: str
    fact_id: str
    section_id: str
    match_confidence: float = Field(description="0.0-1.0")
    match_explanation: str
    is_confirmed: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Evidence(BaseModel):
    """หลักฐานในคดี"""
    evidence_id: str
    case_id: str
    evidence_type: str
    description: str
    submitted_by: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Court(BaseModel):
    """ศาล"""
    court_id: str
    court_name: str
    court_level: Optional[str] = None
    jurisdiction: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Judge(BaseModel):
    """ผู้พิพากษา"""
    judge_id: str
    case_id: str
    judge_name: Optional[str] = None
    role_in_case: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Common Entities (shared across domains) ──────────────────────────────

class Org(BaseModel):
    """องค์กร/หน่วยงาน"""
    org_id: str
    org_name: str
    org_type: Optional[str] = Field(default=None, description="ministerial/department/office/company/etc")
    parent_org_id: Optional[str] = None
    law_regulatory_ref: Optional[str] = None
    access_level: AccessLevel = AccessLevel.PUBLIC
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GeoLocation(BaseModel):
    """สถานที่/พื้นที่"""
    location_id: str
    name: str
    location_type: Optional[str] = Field(default=None, description="province/district/road/building/etc")
    province: Optional[str] = None
    district: Optional[str] = None
    coordinates: Optional[str] = Field(default=None, description="lat,lng")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Event(BaseModel):
    """เหตุการณ์"""
    event_id: str
    event_name: str
    event_type: Optional[str] = None
    event_date: Optional[str] = None
    location_id: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Neo4j Relationship Types ──────────────────────────────────────────────

RELATIONSHIPS = {
    # Law graph
    "HAS_SECTION": "Law → Section",
    "SECTION_HAS_CLAUSE": "Section → Clause",
    "SECTION_HAS_PENALTY": "Section → Penalty",
    "SECTION_GRANTS_RIGHT": "Section → Right",
    "SECTION_IMPOSES_DUTY": "Section → Duty",
    "SECTION_CONFERS_AUTHORITY": "Section → Authority",
    "LAW_HAS_SUBJECT": "Law → Subject",
    "AMENDS": "Amendment → Law",
    "CITES": "Section → Section/Law",
    "RELATED_TO": "Law → Law",

    # Case graph
    "CASE_HAS_FACT": "Case → Fact",
    "CASE_HAS_PERSON": "Case → CasePerson",
    "CASE_HAS_ISSUE": "Case → LegalIssue",
    "CASE_HAS_EVIDENCE": "Case → Evidence",
    "CASE_HEARD_AT": "Case → Court",
    "CASE_JUDGED_BY": "Case → Judge",
    "FACT_APPLIES_TO": "Fact → Section",       # ← Core cross-link!
    "EVIDENCE_SUPPORTS": "Evidence → Fact",
    "ISSUE_REQUIRES_LAW": "LegalIssue → Section",

    # Common
    "WORKS_AT": "CasePerson → Org",
    "LOCATED_AT": "Org/Person/Event → GeoLocation",
    "RELATED_TO_GEO": "Fact/Case → GeoLocation",
    "PERSON_INVOLVED_IN": "CasePerson → Case",
}


# ─── Neo4j Indexes & Constraints ────────────────────────────────────────────

NEO4J_INDEXES = [
    "CREATE INDEX law_id_index IF NOT EXISTS FOR (l:Law) ON (l.law_id)",
    "CREATE INDEX section_id_index IF NOT EXISTS FOR (s:Section) ON (s.section_id)",
    "CREATE INDEX section_law_index IF NOT EXISTS FOR (s:Section) ON (s.law_id)",
    "CREATE INDEX penalty_section_index IF NOT EXISTS FOR (p:Penalty) ON (p.section_id)",
    "CREATE INDEX right_section_index IF NOT EXISTS FOR (r:Right) ON (r.section_id)",
    "CREATE INDEX duty_section_index IF NOT EXISTS FOR (d:Duty) ON (d.section_id)",
    "CREATE INDEX authority_section_index IF NOT EXISTS FOR (a:Authority) ON (a.section_id)",
    "CREATE INDEX case_id_index IF NOT EXISTS FOR (c:Case) ON (c.case_id)",
    "CREATE INDEX fact_case_index IF NOT EXISTS FOR (f:Fact) ON (f.case_id)",
    "CREATE INDEX person_case_index IF NOT EXISTS FOR (p:CasePerson) ON (p.case_id)",
    "CREATE INDEX org_id_index IF NOT EXISTS FOR (o:Org) ON (o.org_id)",
    "CREATE INDEX location_id_index IF NOT EXISTS FOR (l:GeoLocation) ON (l.location_id)",
    "CREATE INDEX access_level_index IF NOT EXISTS FOR (n) WHERE n.access_level IS NOT NULL ON (n.access_level)",
]

NEO4J_CONSTRAINTS = [
    "CREATE CONSTRAINT law_id_unique IF NOT EXISTS FOR (l:Law) REQUIRE l.law_id IS UNIQUE",
    "CREATE CONSTRAINT section_id_unique IF NOT EXISTS FOR (s:Section) REQUIRE s.section_id IS UNIQUE",
    "CREATE CONSTRAINT penalty_id_unique IF NOT EXISTS FOR (p:Penalty) REQUIRE p.penalty_id IS UNIQUE",
    "CREATE CONSTRAINT case_id_unique IF NOT EXISTS FOR (c:Case) REQUIRE c.case_id IS UNIQUE",
    "CREATE CONSTRAINT org_id_unique IF NOT EXISTS FOR (o:Org) REQUIRE o.org_id IS UNIQUE",
]


if __name__ == "__main__":
    print("=== Neo4j Schema ===")
    print(f"Law entity types: Law, Section, Clause, Penalty, Right, Duty, Authority, Subject, Amendment, LegalReference")
    print(f"Case entity types: Case, Fact, CasePerson, LegalIssue, ApplicableLaw, Evidence, Court, Judge")
    print(f"Common entity types: Org, GeoLocation, Event")
    print(f"\nIndexes: {len(NEO4J_INDEXES)}")
    print(f"Constraints: {len(NEO4J_CONSTRAINTS)}")
    print(f"Relationship types: {len(RELATIONSHIPS)}")