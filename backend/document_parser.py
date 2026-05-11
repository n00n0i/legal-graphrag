"""
Legal GraphRAG — Document Parser
================================
ดึง text จาก PDF กฎหมาย (OCS format) และ general documents

Uses: pymupdf (fitz) + marker-pdf (for OCR on scanned docs)

Example:
  from parser import PDFLawParser, PDFGeneralParser
  
  parser = PDFLawParser()
  sections = parser.parse("/path/to/law.pdf")
"""

import re
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field


# ─── Section Pattern Matchers ──────────────────────────────────────────────

# มาตรา patterns — รองรับหลายรูปแบบ
SECTION_PATTERNS = [
    re.compile(r"มาตรา\s*(?:ที่\s*)?(\d+[\/\d]*)", re.IGNORECASE),   # มาตรา 45 / มาตราที่ 45
    re.compile(r"^ข้อ\s*(\d+[\/\d]*)", re.IGNORECASE),               # ข้อ 45
    re.compile(r"^\((\d+[\/\d]*)\)", re.MULTILINE),                   # (45) ตัวเลขในวงเล็บ
    re.compile(r"^§\s*(\d+)", re.MULTILINE),                          # § 45 (civil code style)
    re.compile(r"^Article\s+(\d+)", re.IGNORECASE),                   # Article 45 (EN)
]

# Thai number conversion
THAI_DIGITS = {
    "๐": "0", "๑": "1", "๒": "2", "๓": "3", "๔": "4",
    "๕": "5", "๖": "6", "๗": "7", "๘": "8", "๙": "9"
}


@dataclass
class ParsedSection:
    """มาตราที่แยกได้"""
    section_number: str
    content: str
    raw_text: str
    page_number: int
    chapter: Optional[str] = None
    part: Optional[str] = None


@dataclass
class ParsedLawDocument:
    """ผลลัพธ์จากการ parse กฎหมาย 1 ฉบับ"""
    law_id: str
    title: str
    law_type: str
    effective_date: Optional[str] = None
    gazette_date: Optional[str] = None
    source_path: str
    sections: list[ParsedSection] = field(default_factory=list)
    raw_text: str = ""
    page_count: int = 0


@dataclass
class ChunkResult:
    """chunk หนึ่งสำหรับ indexing"""
    chunk_id: str
    chunk_text: str
    section_refs: list[str]
    page_number: int
    metadata: dict


# ─── Core PDF Parser ─────────────────────────────────────────────────────────

class PDFParser:
    """Base class สำหรับ PDF parsing"""
    
    def __init__(self, use_ocr: bool = False):
        self.use_ocr = use_ocr
    
    def extract_text(self, pdf_path: str) -> tuple[str, int]:
        """Extract text from PDF. Returns (full_text, page_count)"""
        try:
            import fitz
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            text_parts = []
            
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                if text.strip():
                    text_parts.append(text)
                elif self.use_ocr:
                    # TODO: integrate marker-pdf for OCR
                    pass
            
            doc.close()
            return "\n".join(text_parts), page_count
        except Exception as e:
            raise RuntimeError(f"PDF extraction failed: {e}")
    
    @staticmethod
    def normalize_thai_numbers(text: str) -> str:
        """แปลงเลขไทย → เลขอารบิก"""
        for thai, arabic in THAI_DIGITS.items():
            text = text.replace(thai, arabic)
        return text
    
    @staticmethod
    def clean_text(text: str) -> str:
        """ลบ noise ออกจาก text"""
        # ลบเลขหน้ากระดาษ (เช่น "1" ที่ขึ้นต้นบรรทัด)
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            # ลบเลขหน้าที่ติดกับข้อความ
            line = re.sub(r"^\d+\s+(?=[ก-๙])", "", line)
            # ลบช่องว่างทวีคูณ
            line = re.sub(r"\s+", " ", line).strip()
            if line:
                cleaned.append(line)
        return "\n".join(cleaned)


class PDFLawParser(PDFParser):
    """Parser สำหรับเอกสารกฎหมาย (OCS format)"""
    
    def __init__(self, use_ocr: bool = False):
        super().__init__(use_ocr)
    
    def parse(self, pdf_path: str, law_id: Optional[str] = None) -> ParsedLawDocument:
        """
        Parse PDF กฎหมาย → sections + metadata
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        filename = Path(pdf_path).stem
        law_id = law_id or self._generate_law_id(filename)
        
        # 1. Extract text
        full_text, page_count = self.extract_text(pdf_path)
        full_text = self.normalize_thai_numbers(full_text)
        
        # 2. Extract title (usually first non-empty line)
        title = self._extract_title(full_text)
        
        # 3. Detect law type
        law_type = self._detect_law_type(full_text, filename)
        
        # 4. Extract effective date
        effective_date = self._extract_effective_date(full_text)
        
        # 5. Extract sections
        sections = self._extract_sections(full_text)
        
        return ParsedLawDocument(
            law_id=law_id,
            title=title,
            law_type=law_type,
            effective_date=effective_date,
            source_path=pdf_path,
            sections=sections,
            raw_text=full_text,
            page_count=page_count
        )
    
    def _generate_law_id(self, filename: str) -> str:
        """สร้าง law_id จากชื่อไฟล์"""
        # สร้าง id จากชื่อไฟล์
        clean = re.sub(r"[^\wก-๙]", "_", filename)
        # ตัดให้เป็น max 50 ตัวอักษร
        return clean[:50].lower()
    
    def _extract_title(self, text: str) -> str:
        """ดึงชื่อกฎหมายจาก text"""
        lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 5]
        
        # ชื่อกฎหมายมักอยู่ใน 5 บรรทัดแรก
        for line in lines[:10]:
            # ข้ามบรรทัดที่เป็นวันที่หรือเลขหน้า
            if re.match(r"^\d+$", line):
                continue
            if "พระ" in line or "กฎ" in line or "ประมวล" in line or "รัฐธรรมนูญ" in line:
                return line[:200]
        
        return lines[0][:200] if lines else "Unknown"
    
    def _detect_law_type(self, text: str, filename: str) -> str:
        """จำแนกประเภทกฎหมาย"""
        text_lower = text.lower()
        
        if "รัฐธรรมนูญ" in text_lower:
            return "CONSTITUTION"
        if "ประมวล" in text_lower:
            return "CODE"
        if "พระราชบัญญัติ" in text_lower or "พ.ร.บ." in text_lower:
            return "ACT"
        if "พระราชกำหนด" in text_lower or "พ.ร.ก." in text_lower:
            return "EMERGENCY_DECREE"  # หรือ ROYAL_DECREE
        if "กฎกระทรวง" in text_lower:
            return "MINISTERIAL_REGULATION"
        if "พระราชกฤษฎีกา" in text_lower:
            return "ROYAL_DECREE"
        
        return "GENERAL"
    
    def _extract_effective_date(self, text: str) -> Optional[str]:
        """หาวันที่มีผลบังคับใช้"""
        patterns = [
            r"มีผล\s*บังคับ\s*ใช้\s*วันที่\s*(\d{1,2}\s*เดือน\s*\w+\s*\d{4})",
            r"ประกาศ\s*ใน\s*ราชกิจจานุเบกษา\s*วันที่\s*(\d{1,2}\s*เดือน\s*\w+\s*\d{4})",
            r"พ.ศ\.\s*(\d{4})",  # แค่ปี
            r"256[0-9]",  # ปี พ.ศ. 256x
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        
        return None
    
    def _extract_sections(self, text: str) -> list[ParsedSection]:
        """แยกมาตราออกจาก text"""
        sections = []
        lines = text.split("\n")
        
        current_section = None
        current_content = []
        current_page = 1
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # ตรวจสอบว่าเป็นมาตราใหม่หรือไม่
            section_match = None
            for pattern in SECTION_PATTERNS:
                m = pattern.search(line)
                if m and len(line) < 100:  # บรรทัดสั้น = น่าจะเป็นหัวมาตรา
                    section_match = m.group(1)
                    break
            
            if section_match:
                # บันทึกมาตราก่อนหน้า
                if current_section and current_content:
                    content = "\n".join(current_content)
                    if len(content) > 20:  # ข้ามมาตราที่สั้นมาก
                        sections.append(ParsedSection(
                            section_number=current_section,
                            content=self.clean_text(content),
                            raw_text=content,
                            page_number=current_page
                        ))
                
                current_section = section_match
                current_content = [line]
                # ลองหาเลขหน้า
                page_match = re.search(r"-(\d+)-", line)  # เช่น "-45-"
                if page_match:
                    try:
                        current_page = int(page_match.group(1))
                    except:
                        pass
            else:
                if current_section:
                    current_content.append(line)
        
        # บันทึกมาตราสุดท้าย
        if current_section and current_content:
            content = "\n".join(current_content)
            if len(content) > 20:
                sections.append(ParsedSection(
                    section_number=current_section,
                    content=self.clean_text(content),
                    raw_text=content,
                    page_number=current_page
                ))
        
        return sections


class PDFGeneralParser(PDFParser):
    """Parser สำหรับเอกสารทั่วไป (PDF)"""
    
    def __init__(self, chunk_size: int = 1500, overlap: int = 100, use_ocr: bool = False):
        super().__init__(use_ocr)
        self.chunk_size = chunk_size
        self.overlap = overlap
    
    def parse(self, pdf_path: str, doc_id: Optional[str] = None) -> list[ChunkResult]:
        """Parse general document → chunks"""
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        filename = Path(pdf_path).stem
        doc_id = doc_id or filename[:50].lower()
        
        full_text, page_count = self.extract_text(pdf_path)
        full_text = self.normalize_thai_numbers(full_text)
        
        # Chunk using recursive character split
        chunks = self._chunk_text(full_text, doc_id)
        
        return chunks
    
    def _chunk_text(self, text: str, doc_id: str) -> list[ChunkResult]:
        """Recursive character chunking with overlap"""
        chunks = []
        
        # Split by double newlines (paragraphs)
        paragraphs = re.split(r"\n{2,}", text)
        
        current_chunk = ""
        chunk_index = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # ถ้า paragraph เดียวยาวมาก ให้ split ต่อ
            if len(para) > self.chunk_size * 1.5:
                # บันทึก chunk ปัจจุบัน
                if current_chunk:
                    chunks.append(self._make_chunk(doc_id, current_chunk, chunk_index))
                    chunk_index += 1
                    current_chunk = ""
                
                # Split by sentences
                sentences = re.split(r"(?<=[ก-๙]\.)\s+", para)
                for sent in sentences:
                    if len(current_chunk) + len(sent) < self.chunk_size:
                        current_chunk += sent + "\n"
                    else:
                        if current_chunk:
                            chunks.append(self._make_chunk(doc_id, current_chunk, chunk_index))
                            chunk_index += 1
                        current_chunk = sent + "\n"
            
            # ถ้าใส่ paragraph นี้แล้วเกิน chunk_size
            elif len(current_chunk) + len(para) < self.chunk_size:
                current_chunk += para + "\n"
            
            else:
                # เกิน → บันทึก chunk เก่า เริ่ม chunk ใหม่
                chunks.append(self._make_chunk(doc_id, current_chunk, chunk_index))
                chunk_index += 1
                
                # ถ้า overlap > 0 ให้เก็บท้าย chunk เก่ามาด้วย
                if self.overlap > 0 and len(current_chunk) > self.overlap:
                    current_chunk = current_chunk[-self.overlap:] + para + "\n"
                else:
                    current_chunk = para + "\n"
        
        # บันทึก chunk สุดท้าย
        if current_chunk.strip():
            chunks.append(self._make_chunk(doc_id, current_chunk, chunk_index))
        
        return chunks
    
    def _make_chunk(self, doc_id: str, text: str, index: int) -> ChunkResult:
        """สร้าง ChunkResult พร้อม extract section refs"""
        # หา section refs (ม.XX patterns)
        section_refs = []
        for pattern in SECTION_PATTERNS:
            matches = pattern.findall(text)
            section_refs.extend(matches)
        
        return ChunkResult(
            chunk_id=f"{doc_id}_chunk_{index:04d}",
            chunk_text=text.strip(),
            section_refs=list(set(section_refs)),
            page_number=1,  # TODO: map to page
            metadata={}
        )


# ─── OCS Law Fetcher ─────────────────────────────────────────────────────────

class OCSLawFetcher:
    """ดึง PDF กฎหมายจาก OCS website"""
    
    BASE_URL = "https://lawforasean.ocs.go.th/File/files/"
    
    def __init__(self, output_dir: str = "/tmp/laws"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def download_law(self, file_id: str, filename: str) -> str:
        """
        Download law PDF from OCS.
        file_id: เช่น "1532979881.7609a3d099364fe64820fb56c21e1557"
        filename: ชื่อไฟล์ที่ต้องการ
        """
        url = f"{self.BASE_URL}{file_id}.pdf"
        output_path = self.output_dir / filename
        
        import subprocess
        result = subprocess.run(
            ["curl", "-sL", "-o", str(output_path), url],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Download failed: {result.stderr}")
        
        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise RuntimeError(f"Download produced invalid file: {output_path}")
        
        return str(output_path)
    
    def list_available_laws(self) -> list[dict]:
        """List laws that can be downloaded (hardcoded for now)"""
        return [
            {
                "file_id": "1532979881.7609a3d099364fe64820fb56c21e1557",
                "filename": "ป่าสงวนแห่งชาติ_ฉบับ4_2559.pdf",
                "title": "พระราชบัญญัติป่าสงวนแห่งชาติ (ฉบับที่ ๔) พ.ศ. ๒๕๕๙๑"
            }
        ]


if __name__ == "__main__":
    # Test OCS Law Parser
    fetcher = OCSLawFetcher("/tmp/laws")
    laws = fetcher.list_available_laws()
    print(f"Available laws: {len(laws)}")
    for law in laws:
        print(f"  - {law['filename']}: {law['title']}")
    
    # Test parse downloaded PDF
    test_pdf = "/tmp/test_law.pdf"
    if os.path.exists(test_pdf):
        parser = PDFLawParser()
        doc = parser.parse(test_pdf)
        print(f"\nParsed: {doc.title}")
        print(f"Law type: {doc.law_type}")
        print(f"Pages: {doc.page_count}")
        print(f"Sections found: {len(doc.sections)}")
        if doc.sections:
            print(f"First section: ม.{doc.sections[0].section_number} = {doc.sections[0].content[:80]}...")