import numpy as np
from scipy.interpolate import PchipInterpolator


class LinearTailPchip:
    """
    PCHIP внутри диапазона данных и линейная экстраполяция
    по крайним отрезкам вне диапазона.
    """

    def __init__(self, x: np.ndarray, y: np.ndarray):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)

        if len(x) < 2:
            raise ValueError("Для интерполяции требуется минимум 2 точки.")
        if x.shape != y.shape:
            raise ValueError("x и y должны быть одной длины.")
        if not np.all(np.isfinite(x)):
            raise ValueError("В узлах x есть NaN или бесконечность.")
        if not np.all(np.isfinite(y)):
            raise ValueError("В узлах y есть NaN или бесконечность.")
        if np.any(np.diff(x) <= 0):
            raise ValueError("Узлы интерполяции должны быть строго возрастающими.")

        self.x = x
        self.y = y
        self._pchip = PchipInterpolator(self.x, self.y, extrapolate=False)
        self._left_slope = (self.y[1] - self.y[0]) / (self.x[1] - self.x[0])
        self._right_slope = (self.y[-1] - self.y[-2]) / (self.x[-1] - self.x[-2])

    def __call__(self, value: float | np.ndarray) -> float | np.ndarray:
        arr = np.asarray(value, dtype=float)
        scalar_input = arr.ndim == 0
        if scalar_input:
            arr = arr.reshape(1)

        if not np.all(np.isfinite(arr)):
            raise ValueError(f"В интерполятор передано NaN/inf: {arr}")

        out = self._pchip(arr)

        left_mask = arr < self.x[0]
        right_mask = arr > self.x[-1]
        inside_mask = ~(left_mask | right_mask)

        if np.any(left_mask):
            out[left_mask] = self.y[0] + self._left_slope * (arr[left_mask] - self.x[0])

        if np.any(right_mask):
            out[right_mask] = self.y[-1] + self._right_slope * (arr[right_mask] - self.x[-1])

        # Проверяем только точки, которые должны были быть внутри диапазона
        if np.any(np.isnan(out[inside_mask])):
            bad_x = arr[inside_mask][np.isnan(out[inside_mask])]
            raise ValueError(f"Получены NaN внутри диапазона интерполяции для x={bad_x}")

        if scalar_input:
            return float(out[0])
        return out
    
def prepare_monotonic_nodes(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if x.shape != y.shape:
        raise ValueError("x и y должны быть одной длины.")

    finite_mask = np.isfinite(x) & np.isfinite(y)
    x = x[finite_mask]
    y = y[finite_mask]

    if len(x) < 2:
        raise ValueError("После удаления NaN/inf осталось меньше 2 точек.")

    order = np.argsort(x)
    x = x[order]
    y = y[order]

    unique_x = []
    unique_y = []

    i = 0
    n = len(x)
    while i < n:
        current_x = x[i]
        vals = [y[i]]
        i += 1
        while i < n and np.isclose(x[i], current_x, rtol=0.0, atol=1e-12):
            vals.append(y[i])
            i += 1

        unique_x.append(current_x)
        unique_y.append(float(np.mean(vals)))

    unique_x = np.array(unique_x, dtype=float)
    unique_y = np.array(unique_y, dtype=float)

    if len(unique_x) < 2:
        raise ValueError("После обработки узлов осталось меньше 2 точек.")

    if not np.all(np.isfinite(unique_x)) or not np.all(np.isfinite(unique_y)):
        raise ValueError("После обработки узлов остались NaN/inf.")

    if np.any(np.diff(unique_x) <= 0):
        raise ValueError("После обработки узлы всё ещё не строго возрастают.")

    return unique_x, unique_y