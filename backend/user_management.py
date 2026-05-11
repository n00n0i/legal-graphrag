"""
Legal GraphRAG — User Management & Dynamic RBAC
================================================
ระบบลงทะเบียนผู้ใช้ + admin approval + สร้าง role ได้เอง

Flow:
  User register → pending → admin approves → active
                              └── admin rejects → rejected

Role Management:
  Admin สร้าง role ใหม่, กำหนด permissions, assign ให้ user

Usage:
  from user_management import UserManager, RoleManager, Permission
  user_mgr = UserManager(neo4j_driver)
  user_mgr.register(email="...", name="...")
  user_mgr.approve(user_id="...", approver_id="admin123")
"""

import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Literal
from dataclasses import dataclass, field, asdict
from enum import Enum
from pydantic import BaseModel, EmailStr


# ─── Permission System ─────────────────────────────────────────────────────────

class PermissionCategory(str, Enum):
    DOCUMENT = "document"       # เอกสาร
    USER = "user"              # จัดการผู้ใช้
    ROLE = "role"              # จัดการ role
    SYSTEM = "system"          # ระบบ


@dataclass
class Permission:
    """สิทธิ์หนึ่งข้อ"""
    permission_id: str           # เช่น "doc:read:internal"
    name: str                    # "อ่านเอกสารภายใน"
    description: str = ""
    category: PermissionCategory = PermissionCategory.DOCUMENT
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Role:
    """Role ที่มี permissions"""
    role_id: str
    name: str                    # "auditor", "legal_officer"
    display_name: str            # "ผู้ตรวจสอบภายใน"
    description: str = ""
    permissions: list[str] = field(default_factory=list)  # list of permission_id
    is_system: bool = False       # system role = ไม่ให้ลบ
    created_by: str = "system"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class User:
    """ผู้ใช้ระบบ"""
    user_id: str
    email: str
    name: str
    role_id: str
    status: Literal["pending", "active", "rejected", "suspended"] = "pending"
    api_key_hash: Optional[str] = None
    registered_at: datetime = field(default_factory=datetime.utcnow)
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_reason: Optional[str] = None
    suspended_by: Optional[str] = None
    suspended_at: Optional[datetime] = None
    suspended_reason: Optional[str] = None


# ─── Default System Permissions ───────────────────────────────────────────────

SYSTEM_PERMISSIONS = [
    # Document read
    Permission(
        permission_id="doc:read:public",
        name="อ่านเอกสารเผยแพร่",
        description="เข้าถึงเอกสารที่เผยแพร่ทั่วไป",
        category=PermissionCategory.DOCUMENT,
    ),
    Permission(
        permission_id="doc:read:internal",
        name="อ่านเอกสารภายใน",
        description="เข้าถึงเอกสารระดับ INTERNAL",
        category=PermissionCategory.DOCUMENT,
    ),
    Permission(
        permission_id="doc:read:regulated",
        name="อ่านเอกสารระดับ REGULATED",
        description="เข้าถึงเอกสารระดับ REGULATED",
        category=PermissionCategory.DOCUMENT,
    ),
    Permission(
        permission_id="doc:read:confidential",
        name="อ่านเอกสาร CONFIDENTIAL",
        description="เข้าถึงเอกสาร CONFIDENTIAL",
        category=PermissionCategory.DOCUMENT,
    ),
    Permission(
        permission_id="doc:read:classified",
        name="อ่านเอกสาร CLASSIFIED",
        description="เข้าถึงเอกสาร CLASSIFIED",
        category=PermissionCategory.DOCUMENT,
    ),

    # Document write
    Permission(
        permission_id="doc:write:public",
        name="อัพโหลดเอกสาร PUBLIC",
        description="อัพโหลดเอกสารระดับ PUBLIC",
        category=PermissionCategory.DOCUMENT,
    ),
    Permission(
        permission_id="doc:write:internal",
        name="อัพโหลดเอกสาร INTERNAL+",
        description="อัพโหลดเอกสารระดับ INTERNAL ขึ้นไป",
        category=PermissionCategory.DOCUMENT,
    ),

    # User management
    Permission(
        permission_id="user:read",
        name="ดูข้อมูลผู้ใช้",
        description="ดูรายชื่อและข้อมูลผู้ใช้",
        category=PermissionCategory.USER,
    ),
    Permission(
        permission_id="user:approve",
        name="อนุมัติผู้ใช้ใหม่",
        description="อนุมัติหรือปฏิเสธการสมัครสมาชิก",
        category=PermissionCategory.USER,
    ),
    Permission(
        permission_id="user:suspend",
        name="ระงับผู้ใช้",
        description="ระงับหรือยกเลิกการใช้งานผู้ใช้",
        category=PermissionCategory.USER,
    ),

    # Role management
    Permission(
        permission_id="role:create",
        name="สร้าง role ใหม่",
        description="สร้าง role ใหม่ในระบบ",
        category=PermissionCategory.ROLE,
    ),
    Permission(
        permission_id="role:assign",
        name="มอบหมาย role ให้ผู้ใช้",
        description="กำหนด role ให้ผู้ใช้",
        category=PermissionCategory.ROLE,
    ),
    Permission(
        permission_id="role:delete",
        name="ลบ role",
        description="ลบ role ที่ไม่ใช่ system role",
        category=PermissionCategory.ROLE,
    ),
]


# ─── Default System Roles ─────────────────────────────────────────────────────

SYSTEM_ROLES = [
    Role(
        role_id="citizen",
        name="citizen",
        display_name="พลเมือง",
        description="ผู้ใช้ทั่วไป เข้าถึงได้เฉพาะเอกสารเผยแพร่",
        permissions=["doc:read:public"],
        is_system=True,
        created_by="system",
    ),
    Role(
        role_id="officer",
        name="officer",
        display_name="เจ้าหน้าที่รัฐ",
        description="เจ้าหน้าที่รัฐ เข้าถึงเอกสารภายในได้",
        permissions=["doc:read:public", "doc:read:internal"],
        is_system=True,
        created_by="system",
    ),
    Role(
        role_id="lawyer",
        name="lawyer",
        display_name="ทนายความ",
        description="ทนายความ เข้าถึงเอกสารระดับ REGULATED",
        permissions=["doc:read:public", "doc:read:internal", "doc:read:regulated", "doc:write:public"],
        is_system=True,
        created_by="system",
    ),
    Role(
        role_id="admin",
        name="admin",
        display_name="ผู้ดูแลระบบ",
        description="ผู้ดูแลระบบ เข้าถึงทุกอย่าง",
        permissions=[
            "doc:read:public", "doc:read:internal", "doc:read:regulated",
            "doc:read:confidential", "doc:read:classified",
            "doc:write:public", "doc:write:internal",
            "user:read", "user:approve", "user:suspend",
            "role:create", "role:assign", "role:delete",
        ],
        is_system=True,
        created_by="system",
    ),
]


# ─── User Manager ─────────────────────────────────────────────────────────────

class UserManager:
    """
   จัดการผู้ใช้: ลงทะเบียน, อนุมัติ, ปฏิเสธ, ระงับ
    """
    def __init__(self, neo4j_driver):
        self.db = neo4j_driver

    def register(self, email: str, name: str, requested_role: str = "citizen") -> User:
        """ลงทะเบียนผู้ใช้ใหม่ — ได้สถานะ pending"""
        user_id = str(uuid.uuid4())
        
        # ตรวจสอบ email ซ้ำ
        existing = self.db.execute(
            "MATCH (u:User {email: $email}) RETURN u.user_id as uid",
            {"email": email}
        )
        if existing:
            raise ValueError(f"Email {email} already registered")

        # ตรวจสอบ role ที่ขอมีจริง
        role_check = self.db.execute(
            "MATCH (r:Role {role_id: $role_id}) RETURN r.role_id",
            {"role_id": requested_role}
        )
        if not role_check:
            raise ValueError(f"Role {requested_role} does not exist")

        # สร้าง user node
        query = """
        CREATE (u:User {
            user_id: $user_id,
            email: $email,
            name: $name,
            role_id: $role_id,
            status: 'pending',
            registered_at: datetime(),
            requested_role: $requested_role
        })
        RETURN u.user_id as uid
        """
        self.db.execute_write(query, {
            "user_id": user_id,
            "email": email,
            "name": name,
            "role_id": "citizen",  # default เป็น citizen ก่อน approve
            "requested_role": requested_role,
        })
        
        return User(
            user_id=user_id,
            email=email,
            name=name,
            role_id=requested_role,
            status="pending",
        )

    def approve(self, user_id: str, approver_id: str) -> User:
        """อนุมัติผู้ใช้ — เปลี่ยน status เป็น active"""
        query = """
        MATCH (u:User {user_id: $user_id})
        SET u.status = 'active',
            u.approved_by = $approver_id,
            u.approved_at = datetime(),
            u.role_id = u.requested_role
        RETURN u.user_id as uid, u.email as email, u.name as name,
               u.role_id as role_id, u.status as status
        """
        result = list(self.db.execute(query, {
            "user_id": user_id,
            "approver_id": approver_id,
        }))
        
        if not result:
            raise ValueError(f"User {user_id} not found")
        
        r = result[0]
        return User(
            user_id=r["uid"],
            email=r["email"],
            name=r["name"],
            role_id=r["role_id"],
            status=r["status"],
        )

    def reject(self, user_id: str, rejecter_id: str, reason: str = "") -> User:
        """ปฏิเสธผู้ใช้"""
        query = """
        MATCH (u:User {user_id: $user_id})
        SET u.status = 'rejected',
            u.rejected_by = $rejecter_id,
            u.rejected_at = datetime(),
            u.rejected_reason = $reason
        RETURN u.user_id as uid, u.status as status
        """
        result = list(self.db.execute(query, {
            "user_id": user_id,
            "rejecter_id": rejecter_id,
            "reason": reason,
        }))
        
        if not result:
            raise ValueError(f"User {user_id} not found")
        
        return User(user_id=result[0]["uid"], email="", name="", role_id="", status="rejected")

    def suspend(self, user_id: str, suspender_id: str, reason: str = "") -> User:
        """ระงับผู้ใช้"""
        query = """
        MATCH (u:User {user_id: $user_id})
        SET u.status = 'suspended',
            u.suspended_by = $suspender_id,
            u.suspended_at = datetime(),
            u.suspended_reason = $reason
        RETURN u.user_id as uid, u.status as status
        """
        result = list(self.db.execute(query, {
            "user_id": user_id,
            "suspender_id": suspender_id,
            "reason": reason,
        }))
        
        if not result:
            raise ValueError(f"User {user_id} not found")
        
        return User(user_id=result[0]["uid"], email="", name="", role_id="", status="suspended")

    def assign_role(self, user_id: str, role_id: str, assigner_id: str) -> User:
        """มอบหมาย role ใหม่ให้ผู้ใช้"""
        # ตรวจสอบ role มีจริง
        role_check = self.db.execute(
            "MATCH (r:Role {role_id: $role_id}) RETURN r.role_id",
            {"role_id": role_id}
        )
        if not role_check:
            raise ValueError(f"Role {role_id} does not exist")

        query = """
        MATCH (u:User {user_id: $user_id})
        SET u.role_id = $role_id,
            u.updated_at = datetime()
        RETURN u.user_id as uid, u.role_id as role_id, u.status as status
        """
        result = list(self.db.execute(query, {
            "user_id": user_id,
            "role_id": role_id,
        }))
        
        if not result:
            raise ValueError(f"User {user_id} not found")
        
        return User(
            user_id=result[0]["uid"],
            email="",
            name="",
            role_id=result[0]["role_id"],
            status=result[0]["status"],
        )

    def get_user(self, user_id: str) -> Optional[User]:
        """ดึงข้อมูลผู้ใช้"""
        query = """
        MATCH (u:User {user_id: $user_id})
        RETURN u.user_id as uid, u.email as email, u.name as name,
               u.role_id as role_id, u.status as status,
               u.registered_at as registered_at,
               u.approved_by as approved_by, u.approved_at as approved_at
        """
        result = list(self.db.execute(query, {"user_id": user_id}))
        if not result:
            return None
        
        r = result[0]
        return User(
            user_id=r["uid"],
            email=r["email"],
            name=r["name"],
            role_id=r["role_id"],
            status=r["status"],
            registered_at=r["registered_at"],
            approved_by=r.get("approved_by"),
            approved_at=r.get("approved_at"),
        )

    def list_users(self, status_filter: Optional[str] = None, limit: int = 50) -> list[User]:
        """list ผู้ใช้ทั้งหมด"""
        if status_filter:
            query = f"""
            MATCH (u:User)
            WHERE u.status = $status
            RETURN u.user_id as uid, u.email as email, u.name as name,
                   u.role_id as role_id, u.status as status,
                   u.requested_role as requested_role
            ORDER BY u.registered_at DESC
            LIMIT $limit
            """
            results = self.db.execute(query, {"status": status_filter, "limit": limit})
        else:
            query = """
            MATCH (u:User)
            RETURN u.user_id as uid, u.email as email, u.name as name,
                   u.role_id as role_id, u.status as status,
                   u.requested_role as requested_role
            ORDER BY u.registered_at DESC
            LIMIT $limit
            """
            results = self.db.execute(query, {"limit": limit})
        
        return [
            User(
                user_id=r["uid"],
                email=r["email"],
                name=r["name"],
                role_id=r["role_id"],
                status=r["status"],
            )
            for r in results
        ]

    def list_pending(self, limit: int = 50) -> list[User]:
        """list ผู้ใช้ที่รออนุมัติ"""
        return self.list_users(status_filter="pending", limit=limit)


# ─── Role Manager ─────────────────────────────────────────────────────────────

class RoleManager:
    """
   จัดการ roles: สร้าง, แก้ไข, ลบ, ดู permissions
    """
    def __init__(self, neo4j_driver):
        self.db = neo4j_driver

    def create_role(
        self,
        name: str,
        display_name: str,
        permissions: list[str],
        description: str = "",
        created_by: str = "system",
    ) -> Role:
        """สร้าง role ใหม่"""
        role_id = name.lower().replace(" ", "_")
        
        # ตรวจสอบซ้ำ
        existing = self.db.execute(
            "MATCH (r:Role {role_id: $role_id}) RETURN r.role_id",
            {"role_id": role_id}
        )
        if existing:
            raise ValueError(f"Role {role_id} already exists")

        # ตรวจสอบ permissions ที่กำหนดมีจริง
        for perm_id in permissions:
            perm_check = self.db.execute(
                "MATCH (p:Permission {permission_id: $perm_id}) RETURN p.permission_id",
                {"perm_id": perm_id}
            )
            if not perm_check:
                # ถ้า permission ไม่มี ให้ข้าม (อาจเป็น custom permission)
                pass

        query = """
        CREATE (r:Role {
            role_id: $role_id,
            name: $name,
            display_name: $display_name,
            description: $description,
            permissions: $permissions,
            is_system: false,
            created_by: $created_by,
            created_at: datetime(),
            updated_at: datetime()
        })
        RETURN r.role_id as rid
        """
        self.db.execute_write(query, {
            "role_id": role_id,
            "name": name,
            "display_name": display_name,
            "description": description,
            "permissions": permissions,
            "created_by": created_by,
        })
        
        return Role(
            role_id=role_id,
            name=name,
            display_name=display_name,
            description=description,
            permissions=permissions,
            is_system=False,
            created_by=created_by,
        )

    def update_role(
        self,
        role_id: str,
        display_name: Optional[str] = None,
        permissions: Optional[list[str]] = None,
        description: Optional[str] = None,
    ) -> Role:
        """แก้ไข role"""
        # ตรวจสอบไม่ใช่ system role
        check = self.db.execute(
            "MATCH (r:Role {role_id: $role_id}) RETURN r.is_system as is_system",
            {"role_id": role_id}
        )
        if not check:
            raise ValueError(f"Role {role_id} not found")
        if check[0]["is_system"]:
            raise ValueError("Cannot modify system role")

        set_clauses = ["r.updated_at = datetime()"]
        params = {"role_id": role_id}
        
        if display_name is not None:
            set_clauses.append("r.display_name = $display_name")
            params["display_name"] = display_name
        
        if description is not None:
            set_clauses.append("r.description = $description")
            params["description"] = description
        
        if permissions is not None:
            set_clauses.append("r.permissions = $permissions")
            params["permissions"] = permissions
        
        query = f"""
        MATCH (r:Role {{role_id: $role_id}})
        SET {', '.join(set_clauses)}
        RETURN r.role_id as rid, r.name as name, r.display_name as display_name,
               r.permissions as permissions, r.is_system as is_system
        """
        result = list(self.db.execute(query, params))
        
        r = result[0]
        return Role(
            role_id=r["rid"],
            name=r["name"],
            display_name=r["display_name"],
            permissions=r["permissions"],
            is_system=r["is_system"],
        )

    def delete_role(self, role_id: str) -> bool:
        """ลบ role — ไม่ใช่ system role เท่านั้น"""
        check = self.db.execute(
            "MATCH (r:Role {role_id: $role_id}) RETURN r.is_system as is_system",
            {"role_id": role_id}
        )
        if not check:
            raise ValueError(f"Role {role_id} not found")
        if check[0]["is_system"]:
            raise ValueError("Cannot delete system role")
        
        # ตรวจสอบว่าไม่มี user ใช้ role นี้
        user_check = self.db.execute(
            "MATCH (u:User {role_id: $role_id}) RETURN count(u) as cnt",
            {"role_id": role_id}
        )
        if user_check and user_check[0]["cnt"] > 0:
            raise ValueError(f"Cannot delete role: {user_check[0]['cnt']} users are using it")
        
        self.db.execute_write(
            "MATCH (r:Role {role_id: $role_id}) DELETE r",
            {"role_id": role_id}
        )
        return True

    def get_role(self, role_id: str) -> Optional[Role]:
        """ดึงข้อมูล role"""
        query = """
        MATCH (r:Role {role_id: $role_id})
        RETURN r.role_id as rid, r.name as name, r.display_name as display_name,
               r.description as description, r.permissions as permissions,
               r.is_system as is_system
        """
        result = list(self.db.execute(query, {"role_id": role_id}))
        if not result:
            return None
        
        r = result[0]
        return Role(
            role_id=r["rid"],
            name=r["name"],
            display_name=r["display_name"],
            description=r.get("description", ""),
            permissions=r["permissions"],
            is_system=r["is_system"],
        )

    def list_roles(self) -> list[Role]:
        """list ทุก role"""
        query = """
        MATCH (r:Role)
        RETURN r.role_id as rid, r.name as name, r.display_name as display_name,
               r.description as description, r.permissions as permissions,
               r.is_system as is_system
        ORDER BY r.is_system DESC, r.name ASC
        """
        results = self.db.execute(query)
        return [
            Role(
                role_id=r["rid"],
                name=r["name"],
                display_name=r["display_name"],
                description=r.get("description", ""),
                permissions=r["permissions"],
                is_system=r["is_system"],
            )
            for r in results
        ]


# ─── Permission Manager ───────────────────────────────────────────────────────

class PermissionManager:
    """จัดการ permissions"""
    
    def __init__(self, neo4j_driver):
        self.db = neo4j_driver

    def init_permissions(self):
        """สร้าง system permissions ใน Neo4j (เรียกครั้งเดียวตอน init)"""
        for perm in SYSTEM_PERMISSIONS:
            query = """
            MERGE (p:Permission {permission_id: $permission_id})
            SET p.name = $name,
                p.description = $description,
                p.category = $category,
                p.created_at = COALESCE(p.created_at, datetime())
            """
            self.db.execute_write(query, asdict(perm))

    def list_permissions(self, category: Optional[PermissionCategory] = None) -> list[Permission]:
        """list permissions ทั้งหมด"""
        if category:
            query = """
            MATCH (p:Permission {category: $category})
            RETURN p.permission_id as pid, p.name as name, p.description as description
            ORDER BY p.permission_id
            """
            results = self.db.execute(query, {"category": category.value})
        else:
            query = """
            MATCH (p:Permission)
            RETURN p.permission_id as pid, p.name as name, p.description as description,
                   p.category as category
            ORDER BY p.category, p.permission_id
            """
            results = self.db.execute(query)
        
        return [
            Permission(
                permission_id=r["pid"],
                name=r["name"],
                description=r.get("description", ""),
                category=PermissionCategory(r.get("category", "document")),
            )
            for r in results
        ]


# ─── RBAC Checker ──────────────────────────────────────────────────────────────

class RBACChecker:
    """ตรวจสอบสิทธิ์ — ใช้ตอน API call"""
    
    def __init__(self, neo4j_driver):
        self.db = neo4j_driver
        self._role_cache = {}  # cache role → permissions
    
    def get_user_permissions(self, user_id: str) -> list[str]:
        """ดึง permissions ของ user"""
        query = """
        MATCH (u:User {user_id: $user_id})-[:HAS_ROLE]->(r:Role)
        RETURN r.permissions as permissions
        """
        result = list(self.db.execute(query, {"user_id": user_id}))
        
        if result and result[0].get("permissions"):
            return result[0]["permissions"]
        
        # fallback: get from User.role_id
        query2 = """
        MATCH (u:User {user_id: $user_id})
        MATCH (r:Role {role_id: u.role_id})
        RETURN r.permissions as permissions
        """
        result2 = list(self.db.execute(query2, {"user_id": user_id}))
        if result2 and result2[0].get("permissions"):
            return result2[0]["permissions"]
        
        return []

    def has_permission(self, user_id: str, permission_id: str) -> bool:
        """ตรวจสอบว่า user มี permission นี้"""
        perms = self.get_user_permissions(user_id)
        return permission_id in perms

    def has_any_permission(self, user_id: str, permission_ids: list[str]) -> bool:
        """ตรวจสอบว่า user มีอย่างน้อย 1 permission"""
        perms = self.get_user_permissions(user_id)
        return any(p in perms for p in permission_ids)

    def has_all_permissions(self, user_id: str, permission_ids: list[str]) -> bool:
        """ตรวจสอบว่า user มีทุก permission"""
        perms = self.get_user_permissions(user_id)
        return all(p in perms for p in permission_ids)


# ─── Init Schema ───────────────────────────────────────────────────────────────

def init_rbac_schema(neo4j_driver):
    """Initialize RBAC schema in Neo4j — call once"""
    db = neo4j_driver
    
    # Create constraints
    constraints = [
        "CREATE CONSTRAINT user_email IF NOT EXISTS FOR (u:User) REQUIRE u.email IS UNIQUE",
        "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE",
        "CREATE CONSTRAINT role_id IF NOT EXISTS FOR (r:Role) REQUIRE r.role_id IS UNIQUE",
        "CREATE CONSTRAINT permission_id IF NOT EXISTS FOR (p:Permission) REQUIRE p.permission_id IS UNIQUE",
    ]
    
    # Create indexes
    indexes = [
        "CREATE INDEX user_status IF NOT EXISTS FOR (u:User) ON (u.status)",
        "CREATE INDEX role_name IF NOT EXISTS FOR (r:Role) ON (r.name)",
    ]
    
    for c in constraints:
        try:
            db.execute_write(c)
            print(f"  ✓ {c[:50]}...")
        except Exception as e:
            print(f"  ⚠ {str(e)[:80]}")
    
    for idx in indexes:
        try:
            db.execute_write(idx)
            print(f"  ✓ {idx[:50]}...")
        except Exception as e:
            print(f"  ⚠ {str(e)[:80]}")
    
    # Init permissions
    perm_mgr = PermissionManager(db)
    perm_mgr.init_permissions()
    
    # Init system roles
    role_mgr = RoleManager(db)
    for role in SYSTEM_ROLES:
        try:
            role_mgr.create_role(
                name=role.name,
                display_name=role.display_name,
                permissions=role.permissions,
                description=role.description,
                created_by="system",
            )
            print(f"  ✓ Created role: {role.name}")
        except ValueError as e:
            if "already exists" in str(e):
                print(f"  ✓ Role already exists: {role.name}")
            else:
                raise
        except Exception as e:
            print(f"  ⚠ Role {role.name}: {e}")
    
    print("RBAC schema initialized.")


if __name__ == "__main__":
    print("=== RBAC Module ===")
    print(f"System permissions: {len(SYSTEM_PERMISSIONS)}")
    print(f"System roles: {len(SYSTEM_ROLES)}")
    print()
    print("Usage:")
    print("  from user_management import UserManager, RoleManager, PermissionManager")
    print("  from user_management import init_rbac_schema")
    print()
    print("  # Init (call once)")
    print("  init_rbac_schema(neo4j_driver)")
    print()
    print("  # Register user")
    print("  user_mgr = UserManager(neo4j_driver)")
    print("  user_mgr.register(email='...', name='...')")
    print()
    print("  # Approve user")
    print("  user_mgr.approve(user_id='...', approver_id='admin123')")
    print()
    print("  # Create role")
    print("  role_mgr = RoleManager(neo4j_driver)")
    print("  role_mgr.create_role(name='auditor', display_name='ผู้ตรวจสอบ', permissions=['doc:read:public', 'doc:read:internal'])")