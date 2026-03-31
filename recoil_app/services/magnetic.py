import math
from dataclasses import dataclass

G = 9.81
DEFAULT_V_EPS = 1e-6

@dataclass(slots=True)
class MagneticParams:
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
    lya: float = 2.5
    wn0: float = 1.0

def magnetic_force_si(
    v: float,
    wn: float,
    params: MagneticParams,
) -> tuple[float, float]:
    """
    Возвращает модуль силы одного магнитного тормоза в Н и обновлённое wn.
    Сила возвращается без знака направления.
    """
    v_abs = abs(v)
    if v_abs < DEFAULT_V_EPS:
        return 0.0, wn

    gamma = params.gamma
    delta = params.delta
    xm = params.xm
    ym = params.ym
    dh1 = params.dh1
    dh2 = params.dh2
    dm = params.dm
    n = params.n
    mu = params.mu
    bz = params.bz
    lya = params.lya

    d_h1 = 1 if dh1 > 0 else -1 if dh1 < 0 else 0
    d_h2 = 1 if dh2 > 0 else -1 if dh2 < 0 else 0

    h = ym + (dh1 * ((1 - d_h1) / 2)) + (dh2 * ((1 - d_h2) / 2))
    a1 = h / 2 + (dh1 * ((1 + d_h1) / 2))
    a2 = h / 2 + (dh2 * ((1 + d_h2) / 2))

    ya1 = a1 / 2 if a1 / 2 < h / 2 else h / 2
    ya2 = a2 / 2 if a2 / 2 < h / 2 else h / 2

    tj = xm / (4 * v_abs)

    nu1 = (h + dh1 * (1 + d_h1)) / xm
    nu2 = (h + dh2 * (1 + d_h2)) / xm

    w1 = nu1 if nu1 - 1 > 0 else 1 / nu1 if nu1 - 1 != 0 else 1
    w2 = nu2 if nu2 - 1 > 0 else 1 / nu2 if nu2 - 1 != 0 else 1

    rk = (((((w1 - 1 + math.pi / 2) ** 2) / (4 * w1 - 4 + math.pi))
          + (((w2 - 1 + math.pi / 2) ** 2) / (4 * w2 - 4 + math.pi)))
          + math.pi / 2) / (gamma * delta)

    yh = dh1 + dh2 + ym
    yp = yh / 2

    l1 = xm / 4 - (a1 / 2 * (1 - math.pi / 2)) if a1 / 2 < xm / 4 else a1 / 2 - (xm / 4 * (1 - math.pi / 2))
    l2 = xm / 4 - (a2 / 2 * (1 - math.pi / 2)) if a2 / 2 < xm / 4 else a2 / 2 - (xm / 4 * (1 - math.pi / 2))

    lcpk = l1 + l2 + math.pi * yh / 4
    rek = math.sqrt(lcpk / (gamma * rk))
    xpk = (lcpk - yh) / 2

    lbhxk = 2e-7 * xpk * (math.asinh(xpk / rek) + rek / xpk - math.sqrt((rek / xpk) ** 2 + 1))
    lbhyk = 2e-7 * yp * (math.asinh(yp / rek) + rek / yp - math.sqrt((rek / yp) ** 2 + 1))
    lbtxk = 0.5e-7 * mu * xpk
    lbtyk = 0.5e-7 * mu * yp
    mxxk = 2e-7 * xpk * (math.asinh(xpk / yp) + yp / xpk - math.sqrt((yp / xpk) ** 2 + 1))
    myyk = 2e-7 * yp * (math.asinh(yp / xpk) + xpk / yp - math.sqrt((xpk / yp) ** 2 + 1))

    lk = 2 * (lbhxk + lbhyk + lbtxk + lbtyk - mxxk - myyk)
    tk = lk / rk if rk != 0 else 0.0
    tettak = 1 + tk / tj * (math.exp((-tj / tk)) - 1) if tk != 0 else 0.0

    rc = ((((w1 - 1 + math.pi / 2) ** 2) / (4 * w1 - 4 + math.pi))
         + (((w2 - 1 + math.pi / 2) ** 2) / (4 * w2 - 4 + math.pi))
         + (dm * (1 / a1 + 1 / a2)) / 2) * 2 / (gamma * delta)

    lcpc = 2 * (l1 + l2 + dm)
    rec = math.sqrt(lcpc / (gamma * rc))
    xpc = (lcpc - yh) / 2

    lbhxc = 2e-7 * xpc * (math.asinh(xpc / rec) + rec / xpc - math.sqrt((rec / xpc) ** 2 + 1))
    lbhyc = 2e-7 * yp * (math.asinh(yp / rec) + rec / yp - math.sqrt((rec / yp) ** 2 + 1))
    lbtxc = 0.5e-7 * mu * xpc
    lbtyc = 0.5e-7 * mu * yp
    mxxc = 2e-7 * xpc * (math.asinh(xpc / yp) + yp / xpc - math.sqrt((yp / xpc) ** 2 + 1))
    myyc = 2e-7 * yp * (math.asinh(yp / xpc) + xpc / yp - math.sqrt((xpc / yp) ** 2 + 1))

    lc = 2 * (lbhxc + lbhyc + lbtxc + lbtyc - mxxc - myyc)
    tc = lc / rc if rc != 0 else 0.0
    tettac = 1 + tc / tj * (math.exp((-tj / tc)) - 1) if tc != 0 else 0.0

    tp = (delta / math.pi) ** 2 * gamma * 4 * math.pi * 1e-7 * mu * lya
    ex = (8 / math.pi ** 2) * math.exp(-xm / (v_abs * tp)) if tp != 0 else 0.0
    ed = (8 / math.pi ** 2) * math.exp(-dm / (v_abs * tp)) if tp != 0 else 0.0
    wn_next = ed ** 2 * ex * (wn * ex + 1 - ex) + ed * (ex - 1)

    kb = 1 + (v_abs * tp / (2 * xm)) * (8 / math.pi ** 2 - ex) * (wn_next * (1 - ex * ed) - 2 + ed * (ex - 1))
    ft = bz ** 2 * (ya1 + ya2) ** 2 * v_abs * (2 * tettak / rk + 4 * (2 * n - 1) * tettac / rc) * kb ** 2
    return ft, wn_next