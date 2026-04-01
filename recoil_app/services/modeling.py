from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


MODEL_VERSION = "2.0"


@dataclass
class BrakeInputData:
    index: int
    gamma: float
    delta: float
    xm: float
    ym: float
    dh1: float
    dh2: float
    dm: float
    n: int
    mu: float
    bz: float
    lya: float
    wn0: float


@dataclass
class CalculationInputData:
    name: str
    mass: float
    angle_deg: float
    v0: float
    x0: float
    t_max: float
    dt: float
    input_file_name: str
    brakes: list[BrakeInputData] = field(default_factory=list)


@dataclass
class PhaseInterval:
    start_index: int | None = None
    end_index: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    duration: float | None = None


@dataclass
class ForceSeries:
    total: list[float] = field(default_factory=list)
    ext: list[float] = field(default_factory=list)
    spring: list[float] = field(default_factory=list)
    angle: list[float] = field(default_factory=list)
    magnetic_sum: list[float] = field(default_factory=list)
    magnetic_each: list[list[float]] = field(default_factory=list)


@dataclass
class DiagnosticsData:
    termination_reason: str | None = None
    spring_out_of_range: bool = False
    warnings: list[str] = field(default_factory=list)
    dt_stability_status: str | None = None
    dt_stability_details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DerivedMetrics:
    x_max: float | None = None
    v_max: float | None = None
    x_final: float | None = None
    v_final: float | None = None
    a_final: float | None = None
    recoil_end_time: float | None = None
    return_end_time: float | None = None


@dataclass
class ThermalInputData:
    enabled: bool = False
    ambient_temperature: float | None = None
    initial_temperature: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ThermalResultData:
    enabled: bool = False
    temperatures: dict[str, list[float]] = field(default_factory=dict)
    powers: dict[str, list[float]] = field(default_factory=dict)
    energies: dict[str, list[float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationContext:
    variable_parameters: list[dict[str, Any]] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    objectives: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class CalculationModel:
    model_version: str
    meta: dict[str, Any]
    input_data: CalculationInputData
    timeline: dict[str, list[float]]
    phases: dict[str, PhaseInterval]
    forces: ForceSeries
    diagnostics: DiagnosticsData
    derived: DerivedMetrics
    thermal_input: ThermalInputData = field(default_factory=ThermalInputData)
    thermal_result: ThermalResultData = field(default_factory=ThermalResultData)
    optimization_context: OptimizationContext = field(default_factory=OptimizationContext)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def input_snapshot(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "meta": self.meta,
            "input_data": asdict(self.input_data),
            "thermal_input": asdict(self.thermal_input),
            "optimization_context": asdict(self.optimization_context),
        }

    def result_snapshot(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "timeline": self.timeline,
            "phases": {k: asdict(v) for k, v in self.phases.items()},
            "forces": asdict(self.forces),
            "diagnostics": asdict(self.diagnostics),
            "derived": asdict(self.derived),
            "thermal_result": asdict(self.thermal_result),
        }


def _to_float_list(values) -> list[float]:
    return [float(v) for v in values]


def _to_matrix(values) -> list[list[float]]:
    return [[float(v) for v in row] for row in values]


def build_calculation_model(run, brakes, result) -> CalculationModel:
    recoil_phase = PhaseInterval(
        start_index=0 if len(result.t) > 0 else None,
        end_index=result.recoil_end_index,
        start_time=float(result.t[0]) if len(result.t) > 0 else None,
        end_time=result.recoil_end_time,
        duration=(
            float(result.recoil_end_time - result.t[0])
            if len(result.t) > 0 and result.recoil_end_time is not None
            else None
        ),
    )

    return_phase = PhaseInterval(
        start_index=result.recoil_end_index,
        end_index=result.return_end_index,
        start_time=result.recoil_end_time,
        end_time=result.return_end_time,
        duration=(
            float(result.return_end_time - result.recoil_end_time)
            if result.return_end_time is not None and result.recoil_end_time is not None
            else None
        ),
    )

    input_data = CalculationInputData(
        name=run.name,
        mass=float(run.mass),
        angle_deg=float(run.angle_deg),
        v0=float(run.v0),
        x0=float(run.x0),
        t_max=float(run.t_max),
        dt=float(run.dt),
        input_file_name=getattr(run.input_file, "name", "") or "",
        brakes=[
            BrakeInputData(
                index=int(brake.index),
                gamma=float(brake.gamma),
                delta=float(brake.delta),
                xm=float(brake.xm),
                ym=float(brake.ym),
                dh1=float(brake.dh1),
                dh2=float(brake.dh2),
                dm=float(brake.dm),
                n=int(brake.n),
                mu=float(brake.mu),
                bz=float(brake.bz),
                lya=float(brake.lya),
                wn0=float(brake.wn0),
            )
            for brake in brakes
        ],
    )

    forces = ForceSeries(
        total=_to_float_list(result.f_total),
        ext=_to_float_list(result.f_ext),
        spring=_to_float_list(result.f_spring),
        angle=_to_float_list(result.f_angle),
        magnetic_sum=_to_float_list(result.f_magnetic),
        magnetic_each=_to_matrix(result.f_magnetic_each),
    )

    diagnostics = DiagnosticsData(
        termination_reason=result.termination_reason,
        spring_out_of_range=bool(result.spring_out_of_range),
        warnings=[str(w) for w in result.warnings],
        dt_stability_status=None,
        dt_stability_details={},
    )

    derived = DerivedMetrics(
        x_max=float(result.x.max()) if len(result.x) else None,
        v_max=float(result.v.max()) if len(result.v) else None,
        x_final=float(result.x[-1]) if len(result.x) else None,
        v_final=float(result.v[-1]) if len(result.v) else None,
        a_final=float(result.a[-1]) if len(result.a) else None,
        recoil_end_time=result.recoil_end_time,
        return_end_time=result.return_end_time,
    )

    model = CalculationModel(
        model_version=MODEL_VERSION,
        meta={
            "run_id": run.id,
            "calculation_name": run.name,
        },
        input_data=input_data,
        timeline={
            "t": _to_float_list(result.t),
            "x": _to_float_list(result.x),
            "v": _to_float_list(result.v),
            "a": _to_float_list(result.a),
        },
        phases={
            "recoil": recoil_phase,
            "return": return_phase,
        },
        forces=forces,
        diagnostics=diagnostics,
        derived=derived,
    )
    return model