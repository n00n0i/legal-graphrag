"""
Legal GraphRAG — LLM Extraction Prompts
=======================================
Prompts สำหรับ LLM สกัด entities + relationships จาก law documents

Supports: GPT-4o, Azure OpenAI (same schema)

Usage:
  from prompts import EXTRACT_LAW_PROMPT, CLEAN_CHUNK_PROMPT
  response = llm.chat.completions.create(
      messages=[
          {"role": "system", "content": SYSTEM_PROMPT},
          {"role": "user", "content": EXTRACT_LAW_PROMPT.format(doc_text=...)},
      ],
      model="gpt-4o",
      response_format=LawEntities,
  )
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


# ─── Output Schemas (Pydantic) ──────────────────────────────────────────────

class LawType(str, Enum):
    CONSTITUTION = "CONSTITUTION"
    ACT = "ACT"
    ROYAL_DECREE = "ROYAL_DECREE"
    EMERGENCY_DECREE = "EMERGENCY_DECREE"
    CODE = "CODE"
    MINISTERIAL_REGULATION = "MINISTERIAL_REGULATION"
    ROYAL_ORDER = "ROYAL_ORDER"
    CABINET_RESOLUTION = "CABINET_RESOLUTION"
    ORDER = "ORDER"
    NOTIFICATION = "NOTIFICATION"
    GENERAL = "GENERAL"


class ExtractedLaw(BaseModel):
    """หน่วยกฎหมายที่สกัดได้"""
    law_id: str = Field(description="เลขที่กฎหมาย mis_xxx")
    title: str = Field(description="ชื่อกฎหมายตามที่ปรากฏในเอกสาร")
    law_type: LawType
    effective_date: Optional[str] = Field(default=None, description="วันที่มีผลบังคับใช้")
    issued_by: Optional[str] = Field(default=None, description="ผู้ลงนาม/หน่วยงานออก")
    agency_responsible: Optional[str] = Field(default=None, description="หน่วยงานรับผิดชอบ")
    gazette_date: Optional[str] = Field(default=None, description="วันที่ลงประกาศราชกิจจา")


class ExtractedSection(BaseModel):
    """มาตราที่สกัดได้"""
    section_id: str = Field(description="เช่น 'ม.45'")
    section_number: str = Field(description="เช่น '45' หรือ '45/1'")
    title: Optional[str] = Field(default=None, description="หัวข้อมาตรา (ถ้ามี)")
    content: str = Field(description="เนื้อหามาตรา (plain text)")
    chapter: Optional[str] = Field(default=None, description="ภาค/ส่วน (ถ้ามี)")
    part: Optional[str] = Field(default=None, description="ลักษณะ (ถ้ามี)")


class ExtractedPenalty(BaseModel):
    """บทลงโทษที่สกัดได้"""
    penalty_id: str = Field(description="เช่น 'ม.45_โทษ'")
    section_id: str = Field(description="มาตราที่กำหนดโทษ")
    offense_description: str = Field(description="ความผิดที่ระบุ (ชื่อความผิด)")
    penalty_type: str = Field(description="ประเภทโทษ: จำคุก/ปรับ/อาญาจำคุก/ริบทรัพย์")
    penalty_value: Optional[str] = Field(default=None, description="ขนาดโทษ เช่น 'ไม่เกิน 5 ปี' หรือ 'ไม่เกิน 100,000 บาท'")


class ExtractedReference(BaseModel):
    """การอ้างอิงกฎหมายฉบับอื่น"""
    source_section: str = Field(description="มาตราที่อ้างอิง")
    target_law_title: Optional[str] = Field(default=None, description="ชื่อกฎหมายที่อ้างถึง")
    target_section: Optional[str] = Field(default=None, description="มาตราที่อ้างถึง เช่น 'ม.44'")
    reference_type: str = Field(description="ประเภท: cites/amends/repeals/supersedes")
    raw_cite_text: Optional[str] = Field(default=None, description="ข้อความดิบที่ใช้อ้าง เช่น 'ตามมาตรา 44 แห่งพ.ร.บ. ป่าสงวนฯ'")


class LawEntities(BaseModel):
    """Output schema สำหรับ law extraction"""
    law: ExtractedLaw
    sections: list[ExtractedSection] = Field(default_factory=list)
    penalties: list[ExtractedPenalty] = Field(default_factory=list)
    cross_references: list[ExtractedReference] = Field(default_factory=list)
    confidence: float = Field(description="ความมั่นใจของ extraction 0.0-1.0", ge=0, le=1)


class CleanChunkOutput(BaseModel):
    """Output schema สำหรับ chunk cleaning"""
    cleaned_text: str = Field(description="Text สำหรับ embedding — ลบเลขหน้า, normalize, ตัด unnecessary whitespace")
    section_refs: list[str] = Field(default_factory=list, description="มาตราที่ถูกอ้างใน chunk นี้ เช่น ['ม.45', 'ม.46']")
    key_terms: list[str] = Field(default_factory=list, description="คำสำคัญ 5-10 คำสำหรับ metadata")
    summary: str = Field(description="สรุป 1-2 ประโยคของ chunk นี้")


# ─── System Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """คุณเป็นผู้เชี่ยวชาญด้านกฎหมายไทย โดยเฉพาะการวิเคราะห์เอกสารกฎหมายราชการ
คุณต้องสกัด entities และ relationships อย่างแม่นยำ และไม่สร้างข้อมูลที่ไม่มีในเอกสาร
หากไม่แน่ใจ ให้ระบุ null/missing แทนการเดา"""

# ─── Law Extraction Prompt ──────────────────────────────────────────────────

EXTRACT_LAW_PROMPT = """## ภารกิจ: สกัด entities จากเอกสารกฎหมายไทย

### เอกสารต้นทาง:
```text
{doc_text}
```

### คำสั่ง:
1. ระบุชื่อกฎหมาย ประเภท และวันที่มีผลบังคับใช้
2. แยกทุกมาตราออกมา (ม.XX หรือ ข้อ XX)
3. สำหรับแต่ละมาตรา:
   - ระบุเลขมาตรา หัวข้อ (ถ้ามี) และเนื้อหา
   - หากมีบทลงโทษ ให้แยกออกมาด้วย
   - หากมีการอ้างอิงมาตราอื่น ให้บันทึก reference
4. จัดหมวดหมู่ประเภทกฎหมาย:
   - ACT = พระราชบัญญัติ
   - ROYAL_DECREE = พระราชกำหนด
   - CODE = ประมวลกฎหมาย
   - MINISTERIAL_REGULATION = กฎกระทรวง
   - OTHER = คำสั่ง/ประกาศ/อื่นๆ

### รูปแบบ Output:
JSON ที่มีโครงสร้างตาม schema ที่กำหนด
ส่งเฉพาะ JSON เท่านั้น ไม่ต้องมีคำอธิบาย

### ตัวอย่าง section extraction:
```
ม.45 เจ้าของเรือกสักพาอน และเรือสับทราย ต้องจดทะเบียน...
→ section_number: "45"
→ content: "เจ้าของเรือกสักพาอน และเรือสับทราย ต้องจดทะเบียน..."

ม.309 ผู้ใดขับขี่ยานพาหนะโดยประมาท...
→ section_number: "309"
→ content: "ผู้ใดขับขี่ยานพาหนะโดยประมาท ทำให้ผู้อื่นถึงแก่ความตาย..."
```

### ข้อควรระวัง:
- ตัดเลขหน้า ข้อความส่วนหัว/ส่วนท้าย ออกจาก content
- เนื้อหามาตราต้องเป็น plain text ไม่มีตัวเลขมาตราซ้ำซ้อน
- หากมาตรามีการแบ่งข้อย่อย (วรรคหนึ่ง วรรคสอง) ให้รวมเป็น content เดียว
"""


# ─── Chunk Cleaning Prompt ──────────────────────────────────────────────────

CLEAN_CHUNK_PROMPT = """## ภารกิจ: ทำความสะอาด chunk สำหรับ embedding

### Input:
```text
{chunk_text}
```

### คำสั่ง:
1. ลบเลขหน้ากระดาษ ข้อความ header/footer
2. Normalize whitespace (เคาะเดียว, ไม่มีทวีคูณ)
3. ระบุมาตราที่ถูกอ้างใน chunk นี้ (ถ้ามี)
4. ระบุคำสำคัญ 5-10 คำ
5. สรุปสาระสำคัญ 1-2 ประโยค

### Output: JSON ตาม schema"""

# ─── Cross-Reference Detection Prompt ──────────────────────────────────────

CROSS_REF_PROMPT = """## ภารกิจ: ตรวจหาการอ้างอิงกฎหมายในเอกสาร

### Input:
มาตราที่ {section_number} จากกฎหมาย {law_title}:

```text
{section_content}
```

### คำสั่ง:
1. หาข้อความที่อ้างถึงกฎหมายอื่น (เช่น "ตามมาตรา 44 แห่ง พ.ร.บ. ป่าสงวนฯ", "ทบทวนตาม ป.อ. มาตรา 41")
2. ระบุ:
   - กฎหมายที่ถูกอ้าง (ชื่อเต็ม หรือ ประเภทกฎหมาย mis_xxx)
   - มาตราที่ถูกอ้าง
   - ประเภท reference (cites/amends/repeals/supersedes)
3. หากไม่มี reference ให้คืนค่าว่าง

### Output: JSON array ของ references"""

# ─── Case Fact Extraction Prompt (ออกแบบไว้ก่อน) ─────────────────────────────

CASE_FACT_EXTRACTION_PROMPT = """## ภารกิจ: สกัดข้อเท็จจริงจากเอกสารคดี

### Input:
เอกสารคดี (PDF text):

```text
{case_text}
```

### คำสั่ง:
1. ระบุชื่อคู่ความ (โจทก์/จำเลย/ผู้เสียหาย)
2. แยก paragraphs เป็นข้อเท็จจริง (Facts) แต่ละข้อต้องมี:
   - ใคร (actor)
   - ทำอะไร (action)
   - อย่างไร (method)
   - ที่ไหน (location)
   - เมื่อไร (event_time)
3. สำหรับแต่ละ Fact ให้ระบุว่าเข้าข่ายองค์ประกอบความผิดใดบ้าง
4. จำแนกประเภทคดี (อาญา/แพ่ง/ปกครอง/อื่นๆ)

### ตัวอย่าง:
"นาย ก. ขับรถชนนาย ข. เสียชีวิต บริเวณถนนพหลโยธิน กทม. วันที่ 1 มกราคม 2567"
→ actor: "นาย ก."
→ action: "ขับรถชน"
→ result: "เสียชีวิต"
→ location: "ถนนพหลโยธิน กรุงเทพมหานคร"
→ event_time: "1 มกราคม 2567"
→ applicable_sections: ["ม.309", "ม.310", "ม.311"]

### Output: JSON ตาม schema
"""


# ─── Combined Extraction Pipeline ──────────────────────────────────────────

EXTRACTION_PIPELINE = [
    {
        "step": 1,
        "name": "extract_law_entities",
        "prompt": EXTRACT_LAW_PROMPT,
        "output_schema": LawEntities,
        "description": "สกัด Law + Sections + Penalties + References"
    },
    {
        "step": 2,
        "name": "clean_chunks",
        "prompt": CLEAN_CHUNK_PROMPT,
        "output_schema": CleanChunkOutput,
        "description": "ทำความสะอาด section content สำหรับ embedding"
    },
    {
        "step": 3,
        "name": "detect_cross_refs",
        "prompt": CROSS_REF_PROMPT,
        "output_schema": list[ExtractedReference],
        "description": "ตรวจหา cross-references ระหว่างกฎหมาย"
    },
    {
        "step": 4,
        "name": "extract_case_facts",
        "prompt": CASE_FACT_EXTRACTION_PROMPT,
        "output_schema": "CaseEntities",
        "description": "สกัด facts + persons + applicable laws (future)"
    }
]


if __name__ == "__main__":
    import json
    print("=== LLM Extraction Prompts ===")
    for step in EXTRACTION_PIPELINE:
        print(f"\nStep {step['step']}: {step['name']}")
        print(f"  Schema: {step['output_schema']}")
        print(f"  Description: {step['description']}")