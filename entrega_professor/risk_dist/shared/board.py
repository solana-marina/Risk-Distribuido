"""Carregamento do tabuleiro e utilitários geométricos."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from heapq import heappop, heappush
from math import sqrt
from pathlib import Path

import pytmx

from .constants import MAP_ASSET_PATH


@dataclass(frozen=True)
class TerritoryDefinition:
    territory_id: str
    display_name: str
    continent: str
    label_x: float
    label_y: float
    polygon: tuple[tuple[float, float], ...]
    neighbors: tuple[str, ...]
    special_neighbors: tuple[str, ...]


@dataclass(frozen=True)
class BoardDefinition:
    width: int
    height: int
    territories: dict[str, TerritoryDefinition]
    territories_in_order: tuple[str, ...]

    def adjacency(self, territory_id: str) -> tuple[str, ...]:
        return self.territories[territory_id].neighbors

    def display_name(self, territory_id: str) -> str:
        return self.territories[territory_id].display_name

    def continents(self) -> dict[str, tuple[str, ...]]:
        result: dict[str, list[str]] = {}
        for territory_id in self.territories_in_order:
            continent = self.territories[territory_id].continent
            result.setdefault(continent, []).append(territory_id)
        return {key: tuple(value) for key, value in result.items()}

    def special_edges(self) -> tuple[tuple[str, str], ...]:
        edges: set[tuple[str, str]] = set()
        for territory_id, territory in self.territories.items():
            for neighbor in territory.special_neighbors:
                edges.add(tuple(sorted((territory_id, neighbor))))
        return tuple(sorted(edges))


def point_in_polygon(x: float, y: float, polygon: tuple[tuple[float, float], ...]) -> bool:
    """Retorna verdadeiro quando o ponto está dentro do polígono."""
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-9) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside


def _distance_to_segment(
    x: float,
    y: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    ratio = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
    ratio = max(0.0, min(1.0, ratio))
    px = ax + ratio * dx
    py = ay + ratio * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _point_to_polygon_distance(
    x: float,
    y: float,
    polygon: tuple[tuple[float, float], ...],
) -> float:
    inside = point_in_polygon(x, y, polygon)
    min_distance = min(
        _distance_to_segment(x, y, polygon[index - 1], polygon[index])
        for index in range(len(polygon))
    )
    return min_distance if inside else -min_distance


def _polygon_centroid(polygon: tuple[tuple[float, float], ...]) -> tuple[float, float]:
    area = 0.0
    cx = 0.0
    cy = 0.0
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        cross = x1 * y2 - x2 * y1
        area += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if abs(area) < 1e-9:
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    area *= 0.5
    return cx / (6.0 * area), cy / (6.0 * area)


def _best_label_point(
    polygon: tuple[tuple[float, float], ...],
    precision: float = 1.0,
) -> tuple[float, float]:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    min_x = min(xs)
    min_y = min(ys)
    max_x = max(xs)
    max_y = max(ys)
    width = max_x - min_x
    height = max_y - min_y
    cell_size = min(width, height)
    if cell_size <= 1e-6:
        return min_x, min_y
    half = cell_size / 2.0
    cells: list[tuple[float, float, float, float, float]] = []

    def push_cell(center_x: float, center_y: float, radius: float) -> None:
        distance = _point_to_polygon_distance(center_x, center_y, polygon)
        max_distance = distance + radius * sqrt(2.0)
        heappush(cells, (-max_distance, center_x, center_y, radius, distance))

    x = min_x
    while x < max_x:
        y = min_y
        while y < max_y:
            push_cell(x + half, y + half, half)
            y += cell_size
        x += cell_size

    centroid_x, centroid_y = _polygon_centroid(polygon)
    best_x = centroid_x
    best_y = centroid_y
    best_distance = _point_to_polygon_distance(best_x, best_y, polygon)

    bbox_x = (min_x + max_x) / 2.0
    bbox_y = (min_y + max_y) / 2.0
    bbox_distance = _point_to_polygon_distance(bbox_x, bbox_y, polygon)
    if bbox_distance > best_distance:
        best_x = bbox_x
        best_y = bbox_y
        best_distance = bbox_distance

    while cells:
        neg_max_distance, center_x, center_y, radius, distance = heappop(cells)
        if distance > best_distance:
            best_x = center_x
            best_y = center_y
            best_distance = distance
        if -neg_max_distance - best_distance <= precision:
            continue
        half = radius / 2.0
        push_cell(center_x - half, center_y - half, half)
        push_cell(center_x + half, center_y - half, half)
        push_cell(center_x - half, center_y + half, half)
        push_cell(center_x + half, center_y + half, half)

    return best_x, best_y


@lru_cache(maxsize=1)
def load_board(asset_path: str | None = None) -> BoardDefinition:
    """Carrega os metadados do tabuleiro de Risk a partir do arquivo TMX."""
    target = Path(asset_path or MAP_ASSET_PATH)
    tmx_map = pytmx.TiledMap(str(target))
    territories: dict[str, TerritoryDefinition] = {}
    order: list[str] = []
    for obj in tmx_map.objects:
        if getattr(obj, "type", None) != "territory":
            continue
        territory_id = str(obj.properties["territory_id"])
        polygon = tuple((point.x, point.y) for point in obj.points)
        label_x, label_y = _best_label_point(polygon)
        neighbors = tuple(filter(None, str(obj.properties["neighbors"]).split(",")))
        special_neighbors = tuple(
            filter(None, str(obj.properties.get("special_neighbors", "")).split(","))
        )
        territories[territory_id] = TerritoryDefinition(
            territory_id=territory_id,
            display_name=str(obj.properties["display_name"]),
            continent=str(obj.properties["continent"]),
            label_x=label_x,
            label_y=label_y,
            polygon=polygon,
            neighbors=neighbors,
            special_neighbors=special_neighbors,
        )
        order.append(territory_id)
    return BoardDefinition(
        width=tmx_map.width * tmx_map.tilewidth,
        height=tmx_map.height * tmx_map.tileheight,
        territories=territories,
        territories_in_order=tuple(order),
    )
