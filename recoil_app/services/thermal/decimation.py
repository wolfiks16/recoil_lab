"""Урезание временных рядов перед сериализацией в JSON.

Цель — оставить плотность ~target_hz точек/секунду по сегментам, при этом
сохранить «характерные точки»: начало/конец каждого сегмента и пик температуры.
Достаточно простой stride-decimation; LTTB можно прикрутить, если когда-нибудь
понадобится более компактное представление.
"""

from __future__ import annotations

import numpy as np


DEFAULT_TARGET_HZ = 100.0


def decimate_indices(t: np.ndarray, target_hz: float = DEFAULT_TARGET_HZ) -> np.ndarray:
    """Возвращает массив индексов (стрид + последняя точка)."""
    n = len(t)
    if n <= 2:
        return np.arange(n)

    # Грубая средняя плотность
    duration = t[-1] - t[0]
    if duration <= 0:
        return np.arange(n)

    current_hz = (n - 1) / duration
    if current_hz <= target_hz:
        return np.arange(n)

    stride = max(1, int(round(current_hz / target_hz)))
    idx = np.arange(0, n, stride)
    if idx[-1] != n - 1:
        idx = np.append(idx, n - 1)
    return idx


def decimate_per_segment(
    t: np.ndarray,
    segment: np.ndarray,
    cycle_index: np.ndarray,
    target_hz: float = DEFAULT_TARGET_HZ,
) -> np.ndarray:
    """Делает stride-decimation по каждому сегменту независимо.

    На границах сегментов оставляем точки (для разрывного отображения).
    Также сохраняется индекс пика температуры — он берётся в snapshot.py через
    `pick_peak_indices`, объединяется с результатом этой функции.
    """
    n = len(t)
    if n == 0:
        return np.array([], dtype=int)

    # Разбиваем на сегменты по (cycle, segment-name)
    keys = list(zip(cycle_index.tolist(), segment.tolist()))
    boundaries = [0]
    for i in range(1, n):
        if keys[i] != keys[i - 1]:
            boundaries.append(i)
    boundaries.append(n)

    keep: list[int] = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        sub_t = t[start:end]
        local_idx = decimate_indices(sub_t, target_hz=target_hz)
        keep.extend((local_idx + start).tolist())

    return np.array(sorted(set(keep)), dtype=int)


def pick_peak_indices(temp_nodes: np.ndarray) -> set[int]:
    """Возвращает индексы пиков температуры (по узлу) для сохранения при decimation."""
    n_nodes = temp_nodes.shape[1] if temp_nodes.ndim == 2 else 0
    peaks: set[int] = set()
    for k in range(n_nodes):
        peaks.add(int(np.argmax(temp_nodes[:, k])))
    return peaks


def merge_indices(*idx_arrays: np.ndarray | set[int]) -> np.ndarray:
    """Объединяет произвольный набор индексов и возвращает отсортированный массив."""
    union: set[int] = set()
    for arr in idx_arrays:
        if isinstance(arr, set):
            union |= arr
        else:
            union |= set(int(i) for i in arr)
    return np.array(sorted(union), dtype=int)
