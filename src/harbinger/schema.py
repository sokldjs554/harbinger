"""도메인 스키마 — 유비스 마스터류 FMS 에 쌓이는 데이터를 역추론한 모델.

실제 FMS DB 스키마는 공개되어 있지 않으므로, 공개된 기능 설명(체크리스트·NFC/비콘·사진·메모·
고장수리/자재/장비·에너지 4종)에서 역추론했다. 실데이터 연결 시 바뀔 지점은 docs/data-model.md 참고.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum, StrEnum

from pydantic import BaseModel, Field


class SiteArchetype(StrEnum):
    gov_office = "gov_office"  # 정부청사
    hospital = "hospital"  # 병원
    hotel = "hotel"  # 호텔
    office = "office"  # 일반 오피스


class AssetCategory(StrEnum):
    chiller = "chiller"  # 냉동기·냉온수기
    ahu = "ahu"  # 공조기
    pump = "pump"  # 급수·순환 펌프
    boiler = "boiler"  # 보일러
    elevator = "elevator"  # 승강기 (법정점검)
    generator = "generator"  # 비상발전기
    switchgear = "switchgear"  # 수배전반·변압기
    fire_pump = "fire_pump"  # 소방펌프 (법정점검)
    cooling_tower = "cooling_tower"  # 냉각탑
    exhaust_fan = "exhaust_fan"  # 환풍기·배기팬
    auto_door = "auto_door"  # 자동문
    water_tank = "water_tank"  # 급수탱크·저수조


CATEGORY_KO = {
    AssetCategory.chiller: "냉동기",
    AssetCategory.ahu: "공조기",
    AssetCategory.pump: "펌프",
    AssetCategory.boiler: "보일러",
    AssetCategory.elevator: "승강기",
    AssetCategory.generator: "비상발전기",
    AssetCategory.switchgear: "수배전반",
    AssetCategory.fire_pump: "소방펌프",
    AssetCategory.cooling_tower: "냉각탑",
    AssetCategory.exhaust_fan: "환풍기",
    AssetCategory.auto_door: "자동문",
    AssetCategory.water_tank: "급수탱크",
}

# 법정 점검 대상 — 위험도와 무관하게 주기 안에 반드시 점검한다
LEGAL_CATEGORIES = {AssetCategory.elevator, AssetCategory.fire_pump, AssetCategory.generator}
LEGAL_MAX_INTERVAL_DAYS = {
    AssetCategory.elevator: 31,
    AssetCategory.fire_pump: 31,
    AssetCategory.generator: 31,
}

# HVAC 계열 — 사이트 에너지 잔차와 연결되는 설비
HVAC_CATEGORIES = {
    AssetCategory.chiller,
    AssetCategory.ahu,
    AssetCategory.cooling_tower,
    AssetCategory.boiler,
}

# 카테고리별 체크리스트 항목 (유비스 마스터류 점검표를 역추론)
CHECK_ITEMS: dict[AssetCategory, list[str]] = {
    AssetCategory.chiller: ["noise", "vibration", "oil_leak", "temperature", "pressure", "current"],
    AssetCategory.ahu: ["noise", "vibration", "belt", "filter", "temperature", "current"],
    AssetCategory.pump: ["noise", "vibration", "water_leak", "pressure", "current"],
    AssetCategory.boiler: ["noise", "water_leak", "temperature", "pressure", "combustion"],
    AssetCategory.elevator: ["noise", "vibration", "door", "leveling", "operation"],
    AssetCategory.generator: ["oil_leak", "battery", "fuel", "operation", "temperature"],
    AssetCategory.switchgear: ["temperature", "current", "insulation", "odor", "appearance"],
    AssetCategory.fire_pump: ["pressure", "water_leak", "operation", "noise", "appearance"],
    AssetCategory.cooling_tower: ["noise", "vibration", "water_leak", "fill", "fan"],
    AssetCategory.exhaust_fan: ["noise", "vibration", "belt", "operation"],
    AssetCategory.auto_door: ["noise", "operation", "sensor", "appearance"],
    AssetCategory.water_tank: ["water_leak", "level", "appearance", "odor"],
}
ALL_CHECK_ITEMS = sorted({i for items in CHECK_ITEMS.values() for i in items})

CHECK_ITEM_KO = {
    "noise": "소음",
    "vibration": "진동",
    "oil_leak": "누유",
    "water_leak": "누수",
    "temperature": "온도",
    "pressure": "압력",
    "current": "전류",
    "belt": "벨트",
    "filter": "필터",
    "door": "도어",
    "leveling": "착상",
    "operation": "작동",
    "battery": "배터리",
    "fuel": "연료",
    "insulation": "절연",
    "odor": "냄새",
    "appearance": "외관",
    "fill": "충진재",
    "fan": "팬",
    "sensor": "센서",
    "combustion": "연소",
    "level": "수위",
}


class CheckResult(int, Enum):
    good = 0  # 양호
    caution = 1  # 주의
    bad = 2  # 불량


class InspectionMethod(StrEnum):
    nfc = "nfc"
    beacon = "beacon"
    manual = "manual"


class WorkOrderType(StrEnum):
    breakdown = "breakdown"  # 고장수리 (비계획) — 예측 대상
    preventive = "preventive"  # 예방정비 (계획)
    parts = "parts"  # 부품교체 (점검 불량 → 조치)


class Site(BaseModel):
    site_id: str
    name: str
    archetype: SiteArchetype
    floors: int = Field(ge=1)
    opened: date
    region: str = "seoul"


class Inspector(BaseModel):
    inspector_id: str
    site_id: str
    # 아래 세 값은 합성 데이터에서만 알려진 숨은 성향이다. 실데이터에는 없다.
    diligence: float | None = None
    copy_paste_rate: float | None = None
    delay_tendency: float | None = None


class Asset(BaseModel):
    asset_id: str
    site_id: str
    category: AssetCategory
    name: str
    floor: int
    zone: str
    installed: date
    criticality: int = Field(ge=1, le=3)  # 1 낮음 · 3 높음(정전·침수·운행중단급)
    beacon_id: str | None = None


class Inspection(BaseModel):
    inspection_id: str
    asset_id: str
    site_id: str
    inspector_id: str
    scheduled_at: datetime
    performed_at: datetime
    method: InspectionMethod
    dwell_seconds: int = Field(ge=0)
    overall: CheckResult
    items: dict[str, CheckResult]
    memo: str = ""
    photo_count: int = 0


class WorkOrder(BaseModel):
    work_order_id: str
    asset_id: str
    site_id: str
    type: WorkOrderType
    opened_at: datetime
    closed_at: datetime | None
    severity: int = Field(ge=1, le=3)
    downtime_hours: float = 0.0
    parts_cost_krw: int = 0
    description: str = ""


class EnergyReading(BaseModel):
    site_id: str
    day: date
    electricity_kwh: float
    gas_m3: float
    water_m3: float
    heat_gcal: float
    temp_mean_c: float
    occupancy_index: float


# 파케이 테이블 이름 — synth 와 features 가 공유한다
TABLES = ("sites", "inspectors", "assets", "inspections", "workorders", "energy", "latent")
