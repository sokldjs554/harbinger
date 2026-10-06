"""사이트 아키타입과 설비 카테고리 파라미터."""

from __future__ import annotations

from dataclasses import dataclass, field

from harbinger.schema import AssetCategory, SiteArchetype


@dataclass(frozen=True)
class ArchetypeSpec:
    n_sites: int
    assets: tuple[int, int]
    inspectors: tuple[int, int]
    floors: tuple[int, int]
    occupancy: str  # weekday | always | seasonal
    diligence_beta: tuple[float, float]
    copy_paste_beta: tuple[float, float]
    delay_beta: tuple[float, float]
    load: float  # 설비 부하 배수 (열화 속도에 곱)
    elec_base: tuple[float, float]  # 일 kWh 기준치 범위
    gas_base: tuple[float, float]
    water_base: tuple[float, float]
    district_heat: bool
    category_weights: dict[AssetCategory, float] = field(default_factory=dict)
    name_prefix: str = ""


ARCHETYPES: dict[SiteArchetype, ArchetypeSpec] = {
    SiteArchetype.gov_office: ArchetypeSpec(
        n_sites=8,
        assets=(60, 120),
        inspectors=(4, 8),
        floors=(5, 20),
        occupancy="weekday",
        diligence_beta=(5, 2),
        copy_paste_beta=(1, 9),
        delay_beta=(1, 6),
        load=1.0,
        elec_base=(6000, 14000),
        gas_base=(300, 900),
        water_base=(60, 160),
        district_heat=True,
        category_weights={
            AssetCategory.ahu: 4,
            AssetCategory.pump: 3,
            AssetCategory.chiller: 1.2,
            AssetCategory.boiler: 1,
            AssetCategory.elevator: 2,
            AssetCategory.generator: 0.6,
            AssetCategory.switchgear: 1,
            AssetCategory.fire_pump: 0.8,
            AssetCategory.cooling_tower: 0.8,
            AssetCategory.exhaust_fan: 3,
            AssetCategory.auto_door: 1.5,
            AssetCategory.water_tank: 0.6,
        },
        name_prefix="정부청사",
    ),
    SiteArchetype.hospital: ArchetypeSpec(
        n_sites=3,
        assets=(120, 200),
        inspectors=(6, 10),
        floors=(8, 20),
        occupancy="always",
        diligence_beta=(4, 2),
        copy_paste_beta=(1, 7),
        delay_beta=(1.5, 5),
        load=1.35,
        elec_base=(20000, 40000),
        gas_base=(900, 2200),
        water_base=(250, 600),
        district_heat=False,
        category_weights={
            AssetCategory.ahu: 4,
            AssetCategory.pump: 4,
            AssetCategory.chiller: 1.5,
            AssetCategory.boiler: 1.5,
            AssetCategory.elevator: 2.5,
            AssetCategory.generator: 1.2,
            AssetCategory.switchgear: 1.2,
            AssetCategory.fire_pump: 1,
            AssetCategory.cooling_tower: 1,
            AssetCategory.exhaust_fan: 3,
            AssetCategory.auto_door: 2.5,
            AssetCategory.water_tank: 0.8,
        },
        name_prefix="병원",
    ),
    SiteArchetype.hotel: ArchetypeSpec(
        n_sites=4,
        assets=(80, 150),
        inspectors=(3, 6),
        floors=(10, 30),
        occupancy="seasonal",
        diligence_beta=(3, 2),
        copy_paste_beta=(1.5, 5),
        delay_beta=(2, 5),
        load=1.15,
        elec_base=(10000, 25000),
        gas_base=(600, 1500),
        water_base=(200, 500),
        district_heat=False,
        category_weights={
            AssetCategory.ahu: 3.5,
            AssetCategory.pump: 3,
            AssetCategory.chiller: 1.5,
            AssetCategory.boiler: 1.5,
            AssetCategory.elevator: 3,
            AssetCategory.generator: 0.6,
            AssetCategory.switchgear: 1,
            AssetCategory.fire_pump: 1,
            AssetCategory.cooling_tower: 1,
            AssetCategory.exhaust_fan: 2.5,
            AssetCategory.auto_door: 1.5,
            AssetCategory.water_tank: 0.8,
        },
        name_prefix="호텔",
    ),
    SiteArchetype.office: ArchetypeSpec(
        n_sites=10,
        assets=(40, 90),
        inspectors=(2, 4),
        floors=(5, 25),
        occupancy="weekday",
        diligence_beta=(2.5, 2),
        copy_paste_beta=(2, 4),
        delay_beta=(2, 4),
        load=0.9,
        elec_base=(3000, 9000),
        gas_base=(150, 500),
        water_base=(40, 120),
        district_heat=False,
        category_weights={
            AssetCategory.ahu: 4,
            AssetCategory.pump: 2.5,
            AssetCategory.chiller: 1,
            AssetCategory.boiler: 0.8,
            AssetCategory.elevator: 2.5,
            AssetCategory.generator: 0.4,
            AssetCategory.switchgear: 1,
            AssetCategory.fire_pump: 0.8,
            AssetCategory.cooling_tower: 0.7,
            AssetCategory.exhaust_fan: 2.5,
            AssetCategory.auto_door: 1.5,
            AssetCategory.water_tank: 0.5,
        },
        name_prefix="오피스",
    ),
}


@dataclass(frozen=True)
class CategorySpec:
    """카테고리별 열화·위험·점검 파라미터.

    rate      : 하루 평균 열화 증분 (감마 과정 평균)
    age_coef  : 연식 1년당 열화 속도 가산 비율
    beta      : 위험함수의 열화 민감도  h = h0 * exp(beta * D)
    h0        : 열화 0 에서의 일 위험
    season    : summer | winter | none — 부하가 커지는 계절
    insp_every: 점검 주기(일)
    thresholds: 체크리스트 항목별 (주의 임계, 불량 임계) — 작은 값일수록 먼저 나타나는 증상
    downtime  : 고장 시 다운타임(시간) 로그정규 (mu, sigma)
    cost      : 고장 수리비(만원) 로그정규 (mu, sigma)
    """

    rate: float
    age_coef: float
    beta: float
    h0: float
    season: str
    insp_every: int
    thresholds: dict[str, tuple[float, float]]
    downtime: tuple[float, float]
    cost: tuple[float, float]
    criticality: int


CATEGORIES: dict[AssetCategory, CategorySpec] = {
    AssetCategory.chiller: CategorySpec(
        rate=0.0052,
        age_coef=0.05,
        beta=2.4,
        h0=0.00035,
        season="summer",
        insp_every=14,
        thresholds={
            "noise": (0.55, 1.05),
            "vibration": (0.7, 1.2),
            "oil_leak": (0.8, 1.3),
            "temperature": (0.9, 1.35),
            "pressure": (0.95, 1.4),
            "current": (0.85, 1.3),
        },
        downtime=(2.6, 0.6),
        cost=(5.3, 0.7),
        criticality=2,
    ),
    AssetCategory.ahu: CategorySpec(
        rate=0.0048,
        age_coef=0.04,
        beta=2.3,
        h0=0.0004,
        season="summer",
        insp_every=14,
        thresholds={
            "noise": (0.5, 1.0),
            "vibration": (0.65, 1.15),
            "belt": (0.6, 1.1),
            "filter": (0.4, 0.9),
            "temperature": (0.95, 1.4),
            "current": (0.9, 1.35),
        },
        downtime=(1.8, 0.6),
        cost=(4.2, 0.6),
        criticality=1,
    ),
    AssetCategory.pump: CategorySpec(
        rate=0.0058,
        age_coef=0.05,
        beta=2.5,
        h0=0.00042,
        season="none",
        insp_every=14,
        thresholds={
            "noise": (0.55, 1.05),
            "vibration": (0.6, 1.1),
            "water_leak": (0.75, 1.2),
            "pressure": (0.85, 1.3),
            "current": (0.9, 1.35),
        },
        downtime=(1.6, 0.6),
        cost=(4.0, 0.6),
        criticality=2,
    ),
    AssetCategory.boiler: CategorySpec(
        rate=0.0046,
        age_coef=0.05,
        beta=2.3,
        h0=0.0003,
        season="winter",
        insp_every=14,
        thresholds={
            "noise": (0.6, 1.1),
            "water_leak": (0.75, 1.25),
            "temperature": (0.85, 1.3),
            "pressure": (0.8, 1.3),
            "combustion": (0.7, 1.2),
        },
        downtime=(2.4, 0.6),
        cost=(5.0, 0.7),
        criticality=2,
    ),
    AssetCategory.elevator: CategorySpec(
        rate=0.0036,
        age_coef=0.04,
        beta=2.2,
        h0=0.00032,
        season="none",
        insp_every=30,
        thresholds={
            "noise": (0.55, 1.05),
            "vibration": (0.7, 1.2),
            "door": (0.5, 1.0),
            "leveling": (0.8, 1.25),
            "operation": (0.9, 1.35),
        },
        downtime=(2.2, 0.7),
        cost=(5.0, 0.8),
        criticality=3,
    ),
    AssetCategory.generator: CategorySpec(
        rate=0.0028,
        age_coef=0.03,
        beta=2.0,
        h0=0.00018,
        season="none",
        insp_every=30,
        thresholds={
            "oil_leak": (0.6, 1.1),
            "battery": (0.45, 0.95),
            "fuel": (0.9, 1.4),
            "operation": (0.85, 1.3),
            "temperature": (0.95, 1.4),
        },
        downtime=(2.0, 0.7),
        cost=(5.4, 0.8),
        criticality=3,
    ),
    AssetCategory.switchgear: CategorySpec(
        rate=0.0026,
        age_coef=0.04,
        beta=2.6,
        h0=0.00012,
        season="summer",
        insp_every=30,
        thresholds={
            "temperature": (0.55, 1.05),
            "current": (0.65, 1.15),
            "insulation": (0.7, 1.2),
            "odor": (0.85, 1.25),
            "appearance": (0.5, 1.1),
        },
        downtime=(2.8, 0.7),
        cost=(6.0, 0.8),
        criticality=3,
    ),
    AssetCategory.fire_pump: CategorySpec(
        rate=0.0030,
        age_coef=0.04,
        beta=2.2,
        h0=0.0002,
        season="none",
        insp_every=30,
        thresholds={
            "pressure": (0.6, 1.1),
            "water_leak": (0.7, 1.2),
            "operation": (0.8, 1.3),
            "noise": (0.6, 1.1),
            "appearance": (0.5, 1.1),
        },
        downtime=(1.6, 0.6),
        cost=(4.6, 0.7),
        criticality=3,
    ),
    AssetCategory.cooling_tower: CategorySpec(
        rate=0.0050,
        age_coef=0.05,
        beta=2.3,
        h0=0.0003,
        season="summer",
        insp_every=14,
        thresholds={
            "noise": (0.55, 1.05),
            "vibration": (0.65, 1.15),
            "water_leak": (0.7, 1.2),
            "fill": (0.5, 1.0),
            "fan": (0.7, 1.2),
        },
        downtime=(1.8, 0.6),
        cost=(4.4, 0.6),
        criticality=1,
    ),
    AssetCategory.exhaust_fan: CategorySpec(
        rate=0.0055,
        age_coef=0.05,
        beta=2.4,
        h0=0.00045,
        season="none",
        insp_every=21,
        thresholds={
            "noise": (0.5, 1.0),
            "vibration": (0.6, 1.1),
            "belt": (0.55, 1.05),
            "operation": (0.9, 1.35),
        },
        downtime=(1.2, 0.6),
        cost=(3.2, 0.6),
        criticality=1,
    ),
    AssetCategory.auto_door: CategorySpec(
        rate=0.0060,
        age_coef=0.05,
        beta=2.4,
        h0=0.0005,
        season="none",
        insp_every=21,
        thresholds={
            "noise": (0.55, 1.05),
            "operation": (0.6, 1.1),
            "sensor": (0.5, 1.0),
            "appearance": (0.7, 1.25),
        },
        downtime=(1.0, 0.6),
        cost=(3.4, 0.6),
        criticality=1,
    ),
    AssetCategory.water_tank: CategorySpec(
        rate=0.0024,
        age_coef=0.04,
        beta=2.2,
        h0=0.00012,
        season="none",
        insp_every=30,
        thresholds={
            "water_leak": (0.6, 1.1),
            "level": (0.8, 1.3),
            "appearance": (0.5, 1.05),
            "odor": (0.75, 1.25),
        },
        downtime=(2.0, 0.6),
        cost=(4.5, 0.7),
        criticality=2,
    ),
}

# 관측 임계 보정: thresholds 는 "증상이 처음 느껴지는" 단위이고, 체크리스트가 실제로 주의/불량으로
# 넘어가는 지점은 그보다 늦다. (주의, 불량) 임계에 각각 더해 양호 비율이 80 %대가 되도록 보정했다.
OBS_SHIFT = (0.70, 0.80)
# 약신호 창: 양호 판정이지만 성실한 점검자가 메모에 흔적을 남기는 D 구간 = [θ1 - WEAK_WINDOW, θ1 + 0.05)
WEAK_WINDOW = 0.40

# 열화 속도 전역 배율 — 평형 열화 수준과 연간 고장률을 함께 낮춘다
RATE_SCALE = 0.70

# 열화 민감도 배율 — exp(beta·D) 의 beta 에 곱한다. 고장이 돌발보다 열화-주도적이 되게 한다 (오라클 상한 ↑)
BETA_SCALE = 1.40

# 위험함수 전역 배율 — 연간 설비당 비계획 고장 0.6~0.8 건이 되도록 보정
HAZARD_SCALE = 0.22

# 예측 불가능한 돌발 고장(충격) — 열화와 무관한 상수 위험. 완벽한 예측이 불가능하게 만든다.
SHOCK_HAZARD_PER_DAY = 0.00012
