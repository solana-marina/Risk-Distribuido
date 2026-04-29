"""Gera o mapa TMX usando os contornos vetoriais reais do tabuleiro."""

from __future__ import annotations

import re
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement, parse


MAP_WIDTH = 1920
MAP_HEIGHT = 1330
TILE_SIZE = 64
SVG_NAMESPACE = {"svg": "http://www.w3.org/2000/svg"}
SVG_PATH = Path(__file__).resolve().parents[1] / "assets" / "board_source.svg"
SVG_NUDGE_X = 0.0
SVG_NUDGE_Y = -8.0


@dataclass(frozen=True)
class TerritorySeed:
    territory_id: str
    name: str
    continent: str
    center: tuple[int, int]
    neighbors: tuple[str, ...]
    special_neighbors: tuple[str, ...] = ()


TERRITORIES: tuple[TerritorySeed, ...] = (
    TerritorySeed("alaska", "Alaska", "north_america", (165, 250), ("northwest_territory", "alberta", "kamchatka"), ("kamchatka",)),
    TerritorySeed("northwest_territory", "Território do Noroeste", "north_america", (365, 240), ("alaska", "alberta", "ontario", "greenland")),
    TerritorySeed("greenland", "Groenlândia", "north_america", (640, 130), ("northwest_territory", "ontario", "quebec", "iceland"), ("iceland",)),
    TerritorySeed("alberta", "Alberta", "north_america", (340, 445), ("alaska", "northwest_territory", "ontario", "western_united_states")),
    TerritorySeed("ontario", "Ontário", "north_america", (495, 430), ("northwest_territory", "greenland", "quebec", "eastern_united_states", "western_united_states", "alberta")),
    TerritorySeed("quebec", "Quebec", "north_america", (640, 405), ("ontario", "greenland", "eastern_united_states")),
    TerritorySeed("western_united_states", "Oeste dos Estados Unidos", "north_america", (350, 615), ("alberta", "ontario", "eastern_united_states", "central_america")),
    TerritorySeed("eastern_united_states", "Leste dos Estados Unidos", "north_america", (520, 620), ("western_united_states", "ontario", "quebec", "central_america")),
    TerritorySeed("central_america", "América Central", "north_america", (395, 790), ("western_united_states", "eastern_united_states", "venezuela")),
    TerritorySeed("venezuela", "Venezuela", "south_america", (475, 790), ("central_america", "peru", "brazil")),
    TerritorySeed("peru", "Peru", "south_america", (470, 930), ("venezuela", "brazil", "argentina")),
    TerritorySeed("brazil", "Brasil", "south_america", (625, 875), ("venezuela", "peru", "argentina", "north_africa"), ("north_africa",)),
    TerritorySeed("argentina", "Argentina", "south_america", (525, 1140), ("peru", "brazil")),
    TerritorySeed("iceland", "Islândia", "europe", (875, 295), ("greenland", "great_britain", "scandinavia"), ("greenland",)),
    TerritorySeed("great_britain", "Grã-Bretanha", "europe", (900, 455), ("iceland", "scandinavia", "northern_europe", "western_europe")),
    TerritorySeed("scandinavia", "Escandinávia", "europe", (1020, 325), ("iceland", "ukraine", "northern_europe", "great_britain")),
    TerritorySeed("northern_europe", "Norte da Europa", "europe", (1075, 500), ("great_britain", "scandinavia", "ukraine", "southern_europe", "western_europe")),
    TerritorySeed("western_europe", "Oeste da Europa", "europe", (955, 620), ("great_britain", "northern_europe", "southern_europe", "north_africa")),
    TerritorySeed("southern_europe", "Sul da Europa", "europe", (1100, 635), ("western_europe", "northern_europe", "ukraine", "middle_east", "egypt", "north_africa")),
    TerritorySeed("ukraine", "Ucrânia", "europe", (1235, 460), ("scandinavia", "ural", "afghanistan", "middle_east", "southern_europe", "northern_europe")),
    TerritorySeed("north_africa", "Norte da África", "africa", (1020, 800), ("brazil", "western_europe", "southern_europe", "egypt", "east_africa", "congo"), ("brazil",)),
    TerritorySeed("egypt", "Egito", "africa", (1190, 790), ("north_africa", "southern_europe", "middle_east", "east_africa")),
    TerritorySeed("east_africa", "África Oriental", "africa", (1235, 965), ("egypt", "north_africa", "congo", "south_africa", "madagascar", "middle_east")),
    TerritorySeed("congo", "Congo", "africa", (1100, 1010), ("north_africa", "east_africa", "south_africa")),
    TerritorySeed("south_africa", "África do Sul", "africa", (1145, 1170), ("congo", "east_africa", "madagascar")),
    TerritorySeed("madagascar", "Madagascar", "africa", (1340, 1165), ("south_africa", "east_africa")),
    TerritorySeed("ural", "Ural", "asia", (1340, 300), ("ukraine", "siberia", "china", "afghanistan")),
    TerritorySeed("siberia", "Sibéria", "asia", (1480, 230), ("ural", "yakutsk", "irkutsk", "mongolia", "china")),
    TerritorySeed("yakutsk", "Yakutsk", "asia", (1585, 135), ("siberia", "kamchatka", "irkutsk")),
    TerritorySeed("kamchatka", "Camtchatka", "asia", (1780, 300), ("yakutsk", "irkutsk", "mongolia", "japan", "alaska"), ("alaska",)),
    TerritorySeed("irkutsk", "Irkutsk", "asia", (1510, 355), ("siberia", "yakutsk", "kamchatka", "mongolia")),
    TerritorySeed("mongolia", "Mongólia", "asia", (1620, 440), ("siberia", "irkutsk", "kamchatka", "japan", "china")),
    TerritorySeed("japan", "Japão", "asia", (1840, 520), ("kamchatka", "mongolia")),
    TerritorySeed("afghanistan", "Afeganistão", "asia", (1335, 540), ("ukraine", "ural", "china", "india", "middle_east")),
    TerritorySeed("middle_east", "Oriente Médio", "asia", (1285, 725), ("ukraine", "afghanistan", "india", "east_africa", "egypt", "southern_europe")),
    TerritorySeed("india", "Índia", "asia", (1450, 675), ("middle_east", "afghanistan", "china", "siam")),
    TerritorySeed("siam", "Sião", "asia", (1565, 775), ("india", "china", "indonesia"), ("indonesia",)),
    TerritorySeed("china", "China", "asia", (1500, 535), ("ural", "siberia", "mongolia", "siam", "india", "afghanistan")),
    TerritorySeed("indonesia", "Indonésia", "australia", (1505, 980), ("siam", "new_guinea", "western_australia"), ("siam",)),
    TerritorySeed("new_guinea", "Nova Guiné", "australia", (1790, 955), ("indonesia", "western_australia", "eastern_australia")),
    TerritorySeed("western_australia", "Oeste da Austrália", "australia", (1675, 1160), ("indonesia", "new_guinea", "eastern_australia")),
    TerritorySeed("eastern_australia", "Leste da Austrália", "australia", (1825, 1180), ("new_guinea", "western_australia")),
)

def parse_translate(transform: str | None) -> tuple[float, float]:
    if not transform:
        return 0.0, 0.0
    match = re.search(r"translate\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", transform)
    if not match:
        return 0.0, 0.0
    return float(match.group(1)), float(match.group(2))


def tokenize_path(path_data: str) -> list[str]:
    return re.findall(r"[MLCz]|-?\d+(?:\.\d+)?", path_data)


def cubic_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    inv = 1.0 - t
    x = (
        inv * inv * inv * p0[0]
        + 3 * inv * inv * t * p1[0]
        + 3 * inv * t * t * p2[0]
        + t * t * t * p3[0]
    )
    y = (
        inv * inv * inv * p0[1]
        + 3 * inv * inv * t * p1[1]
        + 3 * inv * t * t * p2[1]
        + t * t * t * p3[1]
    )
    return x, y


def cubic_steps(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
) -> int:
    length = (
        ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
        + ((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2) ** 0.5
        + ((p3[0] - p2[0]) ** 2 + (p3[1] - p2[1]) ** 2) ** 0.5
    )
    return max(6, min(28, int(length / 8)))


def parse_svg_polygon(path_data: str) -> list[tuple[float, float]]:
    tokens = tokenize_path(path_data)
    index = 0
    command = ""
    current = (0.0, 0.0)
    start = (0.0, 0.0)
    points: list[tuple[float, float]] = []

    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
        if command == "M":
            current = (float(tokens[index]), float(tokens[index + 1]))
            start = current
            points.append(current)
            index += 2
            command = "L"
            continue
        if command == "L":
            current = (float(tokens[index]), float(tokens[index + 1]))
            points.append(current)
            index += 2
            continue
        if command == "C":
            p1 = (float(tokens[index]), float(tokens[index + 1]))
            p2 = (float(tokens[index + 2]), float(tokens[index + 3]))
            p3 = (float(tokens[index + 4]), float(tokens[index + 5]))
            steps = cubic_steps(current, p1, p2, p3)
            for step in range(1, steps + 1):
                points.append(cubic_point(current, p1, p2, p3, step / steps))
            current = p3
            index += 6
            continue
        if command == "z":
            if points and points[-1] != start:
                points.append(start)
            continue
        raise ValueError(f"Comando SVG não suportado: {command}")
    return points


def perpendicular_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    if start == end:
        return hypot(point[0] - start[0], point[1] - start[1])
    numerator = abs(
        (end[0] - start[0]) * (start[1] - point[1])
        - (start[0] - point[0]) * (end[1] - start[1])
    )
    denominator = hypot(end[0] - start[0], end[1] - start[1])
    return numerator / denominator


def ramer_douglas_peucker(
    points: list[tuple[float, float]],
    tolerance: float,
) -> list[tuple[float, float]]:
    if len(points) <= 2:
        return points
    start = points[0]
    end = points[-1]
    max_distance = 0.0
    split_index = 0
    for index in range(1, len(points) - 1):
        distance = perpendicular_distance(points[index], start, end)
        if distance > max_distance:
            max_distance = distance
            split_index = index
    if max_distance <= tolerance:
        return [start, end]
    left = ramer_douglas_peucker(points[: split_index + 1], tolerance)
    right = ramer_douglas_peucker(points[split_index:], tolerance)
    return left[:-1] + right


def simplify_polygon(points: list[tuple[float, float]], tolerance: float = 1.2) -> list[tuple[float, float]]:
    if len(points) < 4:
        return points
    closed = points + [points[0]]
    simplified = ramer_douglas_peucker(closed, tolerance)
    if len(simplified) > 1 and simplified[0] == simplified[-1]:
        simplified.pop()
    return simplified


def load_svg_polygons() -> dict[str, list[tuple[float, float]]]:
    svg = parse(SVG_PATH).getroot()
    layer = svg.find('.//svg:g[@id="layer4"]', SVG_NAMESPACE)
    if layer is None:
        raise RuntimeError("Camada 'countries' não encontrada no SVG do tabuleiro.")
    translate_x, translate_y = parse_translate(layer.attrib.get("transform"))
    scale_x = MAP_WIDTH / float(svg.attrib["width"])
    scale_y = MAP_HEIGHT / float(svg.attrib["height"])
    polygons: dict[str, list[tuple[float, float]]] = {}
    for path in layer.findall("svg:path", SVG_NAMESPACE):
        raw_id = str(path.attrib["id"])
        territory_id = "yakutsk" if raw_id == "yakursk" else raw_id
        parsed = parse_svg_polygon(str(path.attrib["d"]))
        transformed = [
            ((x + translate_x) * scale_x + SVG_NUDGE_X, (y + translate_y) * scale_y + SVG_NUDGE_Y)
            for x, y in parsed
        ]
        polygons[territory_id] = simplify_polygon(transformed)
    return polygons


def add_property(parent: Element, name: str, value: str) -> None:
    SubElement(parent, "property", attrib={"name": name, "value": value})


def build_tmx() -> ElementTree:
    polygons = load_svg_polygons()
    root = Element(
        "map",
        attrib={
            "version": "1.10",
            "tiledversion": "1.10.2",
            "orientation": "orthogonal",
            "renderorder": "right-down",
            "width": str(MAP_WIDTH // TILE_SIZE),
            "height": str(MAP_HEIGHT // TILE_SIZE),
            "tilewidth": str(TILE_SIZE),
            "tileheight": str(TILE_SIZE),
            "infinite": "0",
            "nextlayerid": "3",
            "nextobjectid": str(len(TERRITORIES) + 1),
        },
    )
    image_layer = SubElement(root, "imagelayer", attrib={"id": "1", "name": "board"})
    SubElement(
        image_layer,
        "image",
        attrib={
            "source": "board.png",
            "width": str(MAP_WIDTH),
            "height": str(MAP_HEIGHT),
        },
    )
    group = SubElement(root, "objectgroup", attrib={"id": "2", "name": "territories"})
    for index, territory in enumerate(TERRITORIES, start=1):
        polygon = polygons.get(territory.territory_id)
        if not polygon:
            raise KeyError(f"Polígono do território '{territory.territory_id}' não foi encontrado no SVG.")
        xs = [point[0] for point in polygon]
        ys = [point[1] for point in polygon]
        min_x = min(xs)
        min_y = min(ys)
        max_x = max(xs)
        max_y = max(ys)
        relative_points = [(x - min_x, y - min_y) for x, y in polygon]
        cx, cy = territory.center
        obj = SubElement(
            group,
            "object",
            attrib={
                "id": str(index),
                "name": territory.name,
                "type": "territory",
                "x": f"{min_x:.3f}",
                "y": f"{min_y:.3f}",
                "width": f"{max_x - min_x:.3f}",
                "height": f"{max_y - min_y:.3f}",
            },
        )
        props = SubElement(obj, "properties")
        add_property(props, "territory_id", territory.territory_id)
        add_property(props, "display_name", territory.name)
        add_property(props, "continent", territory.continent)
        add_property(props, "label_x", str(cx))
        add_property(props, "label_y", str(cy))
        add_property(props, "neighbors", ",".join(territory.neighbors))
        add_property(props, "special_neighbors", ",".join(territory.special_neighbors))
        points = " ".join(f"{x:.3f},{y:.3f}" for x, y in relative_points)
        SubElement(obj, "polygon", attrib={"points": points})
    return ElementTree(root)


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "assets" / "world_map.tmx"
    target.parent.mkdir(parents=True, exist_ok=True)
    tree = build_tmx()
    tree.write(target, encoding="utf-8", xml_declaration=True)
    print(f"Mapa gerado em {target}")


if __name__ == "__main__":
    main()
