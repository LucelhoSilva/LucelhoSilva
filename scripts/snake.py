#!/usr/bin/env python3
"""Gera a cobrinha 3D que percorre o gráfico de contribuições do GitHub e cresce a cada bloco comido.

Sem dependências externas: lê o calendário pela API GraphQL do GitHub e escreve dois SVGs
animados (tema claro e escuro) em projeção oblíqua: cada dia vira um bloco com altura pelo
nível de contribuição, e a cobrinha desliza sobre o tabuleiro fazendo os blocos afundarem.
Como no jogo, ela nunca atravessa o próprio corpo.

Uso: GITHUB_TOKEN=... python3 scripts/snake.py <usuario> [pasta_de_saida]
"""
import json
import os
import sys
import urllib.request
from collections import deque
from xml.sax.saxutils import escape

# Animação
STEP = 0.15          # segundos por casa
SPACING = STEP / 2   # dois gomos por casa: o corpo fica contínuo
START_LEN = 4        # casas ocupadas no início (o logo já tem corpo embaixo desde a entrada)
MAX_LEN = 28         # casas ocupadas depois de comer o último bloco
PAUSE = 2.0          # segundos com o tabuleiro vazio antes de recomeçar
ENTRY_ROW = 3        # linha por onde a cobrinha entra

# Projeção 3D: colunas para a direita, linhas recuando para trás (direita e para cima), altura para cima
ROWS = 7
CW = 15.0                     # largura de uma coluna (px)
DX, DY = 6.0, 12.0            # recuo de cada linha
GAP = 0.12                    # folga entre blocos (fração da casa)
HEIGHTS = [2, 6, 10, 14, 19]  # altura por nível; 0 é a lajota vazia
SNAKE_Z = 8                   # altura do centro da cobrinha acima do chão
LIGHT = (0.03, -0.012)        # sombra dos blocos: deslocamento no chão por px de altura (coluna, linha)

# Logo da Elkys viajando no corpo, logo atrás da cabeça
LOGO_LAG = 4         # centro do logo, em gomos atrás da cabeça (0 é a cabeça)
LOGO_HEIGHT = 24     # altura do hexágono (px)
LOGO_PURPLE = "#480388"
# Logo oficial vetorizado: hexágono e letreiro "e\kys.", numa escala em que o letreiro tem 240 de largura
HEXAGON = (
    "M-4 -138 6 -138 15 -135 106 -98 114 -94 119 -91 123 -87 127 -83 131 -77 134 -72 136 -66 138 -61 138 -53 138 48 "
    "138 56 136 62 133 68 129 76 125 80 121 84 116 87 109 91 15 130 8 132 -1 133 -10 132 -19 129 -108 92 -118 87 "
    "-123 84 -128 79 -134 70 -137 64 -139 59 -140 48 -140 -53 -140 -61 -138 -68 -134 -75 -131 -81 -123 -89 -118 -93 "
    "-112 -96 -19 -135 -12 -137Z"
)
WORDMARK = (
    "M-72 -40 -60 -40 -43 20 -43 21 -54 21 -54 21ZM-34 -40 -22 -40 -22 -3 -5 -24 7 -24 6 -23 -8 -4 10 20 11 21 -2 21 "
    "-17 0 -18 0 -22 0 -22 21 -34 21ZM-99 -26 -94 -26 -90 -26 -86 -24 -82 -22 -78 -18 -77 -16 -75 -11 -74 -6 -74 1 "
    "-109 2 -107 6 -105 9 -103 12 -99 13 -95 13 -90 12 -87 10 -86 7 -75 7 -76 12 -80 18 -86 21 -92 23 -98 23 -102 23 "
    "-106 21 -111 19 -114 16 -117 12 -119 7 -120 2 -120 -4 -119 -8 -118 -13 -115 -18 -111 -22 -108 -24 -103 -26ZM75 -26 "
    "82 -26 87 -25 90 -24 95 -21 97 -18 98 -15 98 -11 88 -11 86 -14 84 -16 82 -17 78 -17 74 -16 72 -15 71 -13 72 -10 "
    "73 -8 77 -7 86 -6 91 -4 96 -1 99 2 100 6 100 9 98 14 96 17 93 20 88 22 82 23 77 23 69 21 65 20 63 17 61 15 59 11 "
    "59 8 59 8 69 8 70 10 73 12 77 14 80 14 85 13 88 10 89 7 87 5 84 3 73 2 68 0 63 -3 61 -7 60 -10 60 -14 62 -18 "
    "63 -21 68 -24ZM10 -25 22 -25 33 9 34 11 35 11 44 -25 56 -25 41 28 39 32 37 35 35 37 32 38 25 40 15 39 15 30 15 29 "
    "25 29 28 28 31 26 33 21 25 20ZM-99 -16 -94 -16 -90 -15 -87 -11 -85 -6 -108 -6 -107 -10 -105 -13 -102 -15ZM107 8 "
    "120 8 120 22 107 22 107 21 107 8Z"
)

# Blocos numa rampa roxa com o #472680 da Elkys numa das pontas (mesma luminosidade dos verdes do GitHub)
# e cobrinha no ciano de destaque da marca, para ela não sumir em cima dos blocos roxos.
THEMES = {
    "github-snake.svg": {
        "id": "l", "empty": "#ebedf0", "levels": ["#D0C2FE", "#AC8BFE", "#844CE6", "#472680"],
        "head": "#128181", "tail": "#44D6D5", "pupil": "#1f2328", "shadow": 0.22, "block_shadow": 0.13,
    },
    "github-snake-dark.svg": {
        "id": "d", "empty": "#21262d", "levels": ["#472680", "#6D3AC2", "#9A6CF8", "#C3AFFF"],
        "head": "#4DE6E6", "tail": "#128181", "pupil": "#0d1117", "shadow": 0.5, "block_shadow": 0.38,
    },
}
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
QUERY = """query($login: String!) {
  user(login: $login) { contributionsCollection { contributionCalendar {
    weeks { contributionDays { contributionLevel weekday } }
  } } }
}"""


def fetch_calendar(user, token):
    """Devolve {(semana, dia_da_semana): nível 0-4} do último ano."""
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": user}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json", "User-Agent": "snake-generator"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise SystemExit(f"Erro da API do GitHub: {payload['errors']}")
    weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    return {(x, day["weekday"]): LEVELS[day["contributionLevel"]] for x, week in enumerate(weeks) for day in week["contributionDays"]}


def length_for(eaten, total):
    """Casas ocupadas depois de comer `eaten` de `total` blocos: cresce de forma contínua até MAX_LEN."""
    return START_LEN + round((MAX_LEN - START_LEN) * eaten / total)


def plan_route(cells):
    """Planeja o trajeto: sempre o bloco mais próximo pelo caminho real, sem atravessar o próprio corpo.

    A cada passo, uma busca em largura sabe quando cada casa do corpo vai ficar livre (a cabeça só
    entra numa casa depois que a cauda passou por ela), e o passo é simulado antes: ela só aceita
    movimentos que deixam espaço livre suficiente para o próprio tamanho, então não entra em becos.
    Devolve o caminho (uma posição por passo) e o passo em que cada bloco foi comido.
    """
    width = max(x for x, _ in cells) + 1
    remaining = {cell for cell, level in cells.items() if level}
    total = len(remaining)
    path = [(x, ENTRY_ROW) for x in range(-4, 0)]  # entra pela esquerda, ainda fora do tabuleiro
    eaten_at = {}

    def search(margin=2):
        """Busca em largura a partir da cabeça. Devolve {casa: (casa_anterior, passos)}.

        margin=2: a casa do corpo só libera um passo depois de a cauda sair (ela pode crescer ao comer);
        margin=0: pode entrar na casa que a cauda está deixando (regra do jogo); None: ignora o corpo.
        """
        head = path[-1]
        length = length_for(len(eaten_at), total)
        free_after = {cell: i + margin for i, cell in enumerate(path[-length:-1])} if margin is not None else {}
        seen, queue = {head: (None, 0)}, deque([head])
        while queue:
            cur = queue.popleft()
            depth = seen[cur][1] + 1
            for dx, dy in ((1, 0), (0, 1), (0, -1), (-1, 0)):
                nxt = (cur[0] + dx, cur[1] + dy)
                if nxt in seen or not (0 <= nxt[0] < width and 0 <= nxt[1] < ROWS):
                    continue
                if depth <= free_after.get(nxt, 0):
                    continue  # o corpo ainda está aqui; a casa pode ser alcançada depois, por um caminho mais longo
                seen[nxt] = (cur, depth)
                queue.append(nxt)
        return seen

    def move_to(cell):
        path.append(cell)
        if cell in remaining:
            remaining.discard(cell)
            eaten_at[cell] = len(path) - 1

    def undo(cell):
        path.pop()
        if eaten_at.get(cell) == len(path):
            del eaten_at[cell]
            remaining.add(cell)

    def space_after(cell):
        """Simula o passo e conta as casas que ela ainda alcança (o corpo vai liberando espaço)."""
        move_to(cell)
        try:
            return len(search()) - 1
        finally:
            undo(cell)

    def first_step(seen, target):
        cell = target
        while seen[cell][0] != path[-1]:
            cell = seen[cell][0]
        return cell

    def closeness(cell, goals):
        return min(abs(cell[0] - g[0]) + abs(cell[1] - g[1]) for g in goals)

    target = None

    def advance(goals):
        """Um passo seguro rumo ao objetivo mais próximo; replaneja sempre, porque o corpo muda enquanto ela anda."""
        nonlocal target
        seen, head = search(), path[-1]
        moves = [c for c, (_, depth) in seen.items() if depth == 1]
        if not moves:  # totalmente cercada: segue a cauda (regra do jogo) ou, em último caso, ignora o corpo
            for margin in (0, None):
                relaxed = search(margin)
                moves = [c for c, (_, depth) in relaxed.items() if depth == 1]
                if moves:
                    break
            target = None
            move_to(min(moves, key=lambda c: (closeness(c, goals), c)))
            return
        if target not in goals or target not in seen:
            reachable = [c for c in goals if c in seen]
            target = (min(reachable, key=lambda c: (seen[c][1], 0 if head[0] == c[0] or head[1] == c[1] else 1, c))
                      if reachable else None)
        length = length_for(len(eaten_at), total)
        space = {m: space_after(m) for m in moves}
        safe = [m for m in moves if space[m] >= length]
        preferred = first_step(seen, target) if target else None
        if preferred in safe:
            move_to(preferred)
            return
        target = None  # o caminho mais curto é arriscado: escolhe outro passo e replaneja no próximo
        if safe:
            move_to(min(safe, key=lambda m: (closeness(m, goals), -space[m], m)))
        else:
            move_to(max(moves, key=lambda m: (space[m], m)))

    limit = 30 * width * ROWS  # trava de segurança: a Action nunca fica presa num laço
    while remaining and len(path) < limit:
        advance(remaining)
    exits, target = {(width - 1, y) for y in range(ROWS)}, None
    while path[-1] not in exits and len(path) < limit + width * ROWS:  # sai pela borda direita
        advance(exits)
    path.extend((x, path[-1][1]) for x in range(width, width + MAX_LEN + 3))
    return path, eaten_at


def lengths_per_step(steps, eaten_at):
    """Casas ocupadas em cada passo do caminho."""
    eaten_by_step = [0] * (steps + 1)
    for s in eaten_at.values():
        eaten_by_step[s] += 1
    total, eaten, lengths = len(eaten_at), 0, []
    for count in eaten_by_step:
        eaten += count
        lengths.append(length_for(eaten, total))
    return lengths


def mix(color_a, color_b, k):
    a = [int(color_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(color_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(p + (q - p) * k):02X}" for p, q in zip(a, b))


def shade(color, factor):
    return mix(color, "#000000", 1 - factor)


def project(u, v, z=0.0):
    """Coordenadas da grade (u = coluna, v = linha, z = altura) em pixels."""
    return u * CW + (ROWS - v) * DX, v * DY - z


def hull(points):
    """Fecho convexo de pontos 2D (cadeia monótona), usado na sombra dos blocos."""
    pts = sorted(set(points))
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for q in pts:
        while len(lower) > 1 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    for q in reversed(pts):
        while len(upper) > 1 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return lower[:-1] + upper[:-1]


def block_defs(level, top, p):
    """Degradês das três faces de um nível: topo mais claro à esquerda, laterais escurecendo para baixo."""
    grad = lambda name, a, b, down: (
        f'<linearGradient id="{p}g{level}{name}" x1="0" y1="0" x2="{0 if down else 1}" y2="{1 if down else 0}">'
        f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient>')
    return (grad("t", mix(top, "#FFFFFF", 0.16), top, False)
            + grad("f", shade(top, 0.82), shade(top, 0.68), True)
            + grad("r", shade(top, 0.62), shade(top, 0.48), True))


def block(level, top, p, shadow):
    """Bloco em coordenadas locais, com origem no canto frontal esquerdo da base.

    Luz vindo de cima, da frente e da esquerda: topo claro, frente média e lateral direita mais escura,
    um fio de luz nas arestas iluminadas e a sombra projetada no chão, para a direita e para trás.
    """
    size, h = 1 - 2 * GAP, HEIGHTS[level]
    offset = lambda du, dv, z: (du * CW - dv * DX, dv * DY - z)
    pts = lambda seq: " ".join("%.1f,%.1f" % q for q in seq)
    face = lambda seq, fill: f'<polygon points="{pts(offset(*q) for q in seq)}" fill="{fill}"/>'
    base = [(0, 0, 0), (size, 0, 0), (size, -size, 0), (0, -size, 0)]
    out = ""
    if shadow:
        cast = [(u + LIGHT[0] * h, v + LIGHT[1] * h, 0) for u, v, _ in base]
        out += f'<polygon points="{pts(hull([offset(*q) for q in base + cast]))}" fill="#000000" fill-opacity="{shadow}"/>'
    out += (face([(0, 0, 0), (size, 0, 0), (size, 0, h), (0, 0, h)], f"url(#{p}g{level}f)")
            + face([(size, 0, 0), (size, -size, 0), (size, -size, h), (size, 0, h)], f"url(#{p}g{level}r)")
            + face([(0, 0, h), (size, 0, h), (size, -size, h), (0, -size, h)], f"url(#{p}g{level}t)"))
    if level:
        out += (f'<polyline points="{pts(offset(*q) for q in [(0, -size, h), (0, 0, h), (size, 0, h)])}" '
                'fill="none" stroke="#FFFFFF" stroke-opacity="0.35" stroke-width="0.6" stroke-linejoin="round"/>')
    return out


def bead(radius, color, p):
    """Gomo esférico: cor base, sombreamento difuso e um brilho especular no alto, à esquerda."""
    r, cx, cy = radius, -0.34 * radius, -0.4 * radius
    return (f'<circle r="{r:.1f}" fill="{color}"/><circle r="{r:.1f}" fill="url(#{p}shine)"/>'
            f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{0.3 * r:.1f}" ry="{0.18 * r:.1f}" '
            f'transform="rotate(-35 {cx:.1f} {cy:.1f})" fill="url(#{p}spec)"/>')


def route_path(path, z):
    """Caminho SVG só com as curvas, já projetado na altura z."""
    corners = [path[0]]
    for prev, cur, nxt in zip(path, path[1:], path[2:]):
        if (cur[0] - prev[0], cur[1] - prev[1]) != (nxt[0] - cur[0], nxt[1] - cur[1]):
            corners.append(cur)
    corners.append(path[-1])
    return "M" + " L".join("%.1f %.1f" % project(c[0] + 0.5, c[1] + 0.5, z) for c in corners)


def render(cells, path, eaten_at, theme):
    steps = len(path) - 1
    move = steps * STEP
    cycle = move + PAUSE
    lengths = lengths_per_step(steps, eaten_at)
    columns = max(x for x, _ in cells) + 1
    p = theme["id"] + "-"  # ids únicos por tema: os dois SVGs podem estar na mesma página
    frac = lambda seconds: f"{min(max(seconds, 0.001) / cycle, 1):.5f}"
    dur = f'dur="{cycle:.2f}s" repeatCount="indefinite"'
    use = lambda ref: f'href="#{p}{ref}" xlink:href="#{p}{ref}"'
    pupil = theme["pupil"]

    # Tabuleiro: lajotas vazias embaixo de tudo e blocos por cima, sempre de trás para a frente.
    tiles, blocks = [], []
    for (x, y), level in sorted(cells.items(), key=lambda item: (item[0][1], item[0][0])):
        fx, fy = project(x + GAP, y + 1 - GAP)
        tiles.append(f'<use {use("t")} x="{fx:.1f}" y="{fy:.1f}"/>')
        if level:
            sink = ""
            if (x, y) in eaten_at:  # afunda no chão quando a cabeça chega
                eaten = eaten_at[(x, y)] * STEP
                sink = (f'<animateTransform attributeName="transform" type="scale" calcMode="linear" {dur} '
                        f'values="1 1;1 1;1 0;1 0" keyTimes="0;{frac(eaten - 0.6 * STEP)};{frac(eaten + 0.2 * STEP)};1"/>')
            blocks.append(f'<g transform="translate({fx:.1f} {fy:.1f})"><g><use {use(f"b{level}")}/>{sink}</g></g>')

    def motion(delay, route="route", rotate=False):
        turn = ' rotate="auto"' if rotate else ""
        return (f'<animateMotion {dur} begin="{delay:.3f}s" calcMode="linear" keyPoints="0;1;1" '
                f'keyTimes="0;{frac(move)};1"{turn}><mpath {use(route)}/></animateMotion>')

    def appear(j, delay):
        """Gomo j aparece quando a cobrinha já ocupa casas suficientes para ele."""
        needed = (j + 2) // 2
        if needed <= START_LEN:
            return f'<set attributeName="opacity" to="1" begin="{delay:.3f}s"/>'
        first = next(s for s, length in enumerate(lengths) if length >= needed)
        return (f'<animate attributeName="opacity" calcMode="discrete" {dur} begin="{delay:.3f}s" '
                f'values="0;1" keyTimes="0;{frac(first * STEP - delay)}"/>')

    gomos = 2 * MAX_LEN - 1
    radius_of = lambda j: 8.4 if j == 0 else 6.6 - 2.2 * j / (gomos - 1)

    shadows, body = [], []
    for j in range(gomos - 1, -1, -1):  # da cauda para a cabeça, para a cabeça ficar por cima
        radius, delay = radius_of(j), j * SPACING
        show = appear(j, delay)
        shadows.append(
            f'<ellipse rx="{radius * 1.3:.1f}" ry="{radius * 0.58:.1f}" fill="url(#{p}sg)" opacity="0">'
            f'{motion(delay, "shadow")}{show}</ellipse>'
        )
        if j:
            look = bead(radius, mix(theme["head"], theme["tail"], j / (gomos - 1)), p)
            body.append(f'<g opacity="0">{look}{motion(delay)}{show}</g>')

    # Logo oficial da Elkys viajando no corpo, logo atrás da cabeça, sempre de pé para continuar legível:
    # sombra macia embaixo, filete branco em volta e um brilho suave no hexágono.
    scale, lag = LOGO_HEIGHT / 271, LOGO_LAG * SPACING  # o hexágono tem 271 unidades de altura
    logo = f'transform="scale({scale:.4f}) translate(1 2.5)"'  # centro do hexágono no ponto do corpo
    label = (
        f'<g opacity="0"><g {logo}><path d="{HEXAGON}" transform="translate(6 9)" fill="#000000" fill-opacity="0.22"/>'
        f'<path d="{HEXAGON}" fill="{LOGO_PURPLE}" stroke="#FFFFFF" stroke-width="{1.3 / scale:.1f}" stroke-linejoin="round" '
        f'paint-order="stroke"/><path d="{HEXAGON}" fill="url(#{p}gloss)"/><path d="{WORDMARK}" fill="#FFFFFF" fill-rule="evenodd"/></g>'
        f'{motion(lag)}<set attributeName="opacity" to="1" begin="{lag:.3f}s"/></g>'
    )

    # Cabeça: gomo maior, olhos com brilho, um sorriso e a língua que dá uma olhadinha de vez em quando.
    head = (
        f'<g opacity="0">{bead(radius_of(0), theme["head"], p)}{motion(0)}{appear(0, 0)}</g>'
        '<g opacity="0"><circle cx="3.2" cy="-3.5" r="2.6" fill="#ffffff"/><circle cx="3.2" cy="3.5" r="2.6" fill="#ffffff"/>'
        f'<circle cx="4.1" cy="-3.5" r="1.3" fill="{pupil}"/><circle cx="4.1" cy="3.5" r="1.3" fill="{pupil}"/>'
        '<circle cx="3.5" cy="-4.2" r="0.6" fill="#ffffff"/><circle cx="3.5" cy="2.8" r="0.6" fill="#ffffff"/>'
        f'<path d="M6.8,-1.6 Q8.6,0 6.8,1.6" fill="none" stroke="{pupil}" stroke-opacity="0.55" stroke-width="0.7" stroke-linecap="round"/>'
        '<path d="M8.4,0 L11.8,0 M11.8,0 L13.1,-1.1 M11.8,0 L13.1,1.1" fill="none" stroke="#F06292" stroke-width="1" '
        'stroke-linecap="round" opacity="0"><animate attributeName="opacity" calcMode="discrete" dur="3.3s" repeatCount="indefinite" '
        'values="0;1;0;1;0" keyTimes="0;0.78;0.84;0.88;0.94"/></path>'
        f'{motion(0, rotate=True)}{appear(0, 0)}</g>'
    )

    left, right = -12, columns * CW + ROWS * DX + 12
    top, bottom = -(HEIGHTS[-1] + 18), ROWS * DY + 10
    defs = (
        f'<radialGradient id="{p}shine" cx="0.36" cy="0.32" r="0.72">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="0.7"/><stop offset="0.3" stop-color="#ffffff" stop-opacity="0.16"/>'
        '<stop offset="0.72" stop-color="#000000" stop-opacity="0.06"/><stop offset="1" stop-color="#000000" stop-opacity="0.45"/>'
        '</radialGradient>'
        f'<radialGradient id="{p}spec"><stop offset="0" stop-color="#ffffff" stop-opacity="0.9"/>'
        '<stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="{p}gloss" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" stop-opacity="0.22"/>'
        '<stop offset="0.5" stop-color="#ffffff" stop-opacity="0"/><stop offset="1" stop-color="#000000" stop-opacity="0.12"/></linearGradient>'
        f'<radialGradient id="{p}sg"><stop offset="0" stop-color="#000000" stop-opacity="{theme["shadow"]}"/>'
        f'<stop offset="0.55" stop-color="#000000" stop-opacity="{theme["shadow"] * 0.7:.2f}"/>'
        '<stop offset="1" stop-color="#000000" stop-opacity="0"/></radialGradient>'
        + "".join(block_defs(level, color, p) for level, color in enumerate([theme["empty"]] + theme["levels"]))
        + f'<g id="{p}t">{block(0, theme["empty"], p, 0)}</g>'
        + "".join(f'<g id="{p}b{level}">{block(level, color, p, theme["block_shadow"])}</g>'
                  for level, color in enumerate(theme["levels"], start=1))
        + f'<path id="{p}route" d="{route_path(path, SNAKE_Z)}"/><path id="{p}shadow" d="{route_path(path, 0)}"/>'
    )
    title = "Cobrinha 3D comendo o gráfico de contribuições"
    desc = (f"A cobrinha, levando o logo da Elkys no corpo, percorre {len(eaten_at)} dias com contribuições do último ano "
            f"e cresce de {START_LEN} para {MAX_LEN} casas.")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="{left} {top} {right - left:.0f} {bottom - top:.0f}" width="{right - left:.0f}" height="{bottom - top:.0f}" '
        f'role="img" aria-labelledby="{p}title {p}desc"><title id="{p}title">{escape(title)}</title><desc id="{p}desc">{escape(desc)}</desc>'
        f'<defs>{defs}</defs><g>{"".join(tiles)}</g><g>{"".join(blocks)}</g>'
        f'<g>{"".join(shadows)}</g><g>{"".join(body)}{label}{head}</g></svg>\n'
    )


def collisions(path, eaten_at):
    """Quantas vezes a cabeça entra numa casa ainda ocupada pelo corpo."""
    lengths = lengths_per_step(len(path) - 1, eaten_at)
    return sum(1 for s in range(1, len(path)) if path[s] in set(path[max(0, s - lengths[s - 1]):s]))


def sweep_route(cells):
    """Rota de reserva para gráficos quase cheios: varre coluna por coluna em zigue-zague.

    Nunca passa duas vezes pela mesma casa, então é impossível atravessar o próprio corpo.
    """
    width = max(x for x, _ in cells) + 1
    remaining = {cell for cell, level in cells.items() if level}
    path = [(x, ENTRY_ROW) for x in range(-4, 0)] + [(-1, y) for y in range(ENTRY_ROW - 1, -1, -1)]
    eaten_at = {}
    for x in range(width):
        for y in (range(ROWS) if x % 2 == 0 else range(ROWS - 1, -1, -1)):
            path.append((x, y))
            if (x, y) in remaining:
                remaining.discard((x, y))
                eaten_at[(x, y)] = len(path) - 1
    path.extend((x, path[-1][1]) for x in range(width, width + MAX_LEN + 3))
    return path, eaten_at


def plan(cells):
    """Usa a rota inteligente; se ela cruzar o próprio corpo (gráficos quase cheios), usa a varredura."""
    path, eaten_at = plan_route(cells)
    if collisions(path, eaten_at):
        path, eaten_at = sweep_route(cells)
    return path, eaten_at


def main():
    if len(sys.argv) < 2 or not os.environ.get("GITHUB_TOKEN"):
        raise SystemExit("Uso: GITHUB_TOKEN=... python3 scripts/snake.py <usuario> [pasta_de_saida]")
    user, out_dir = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "dist"
    cells = fetch_calendar(user, os.environ["GITHUB_TOKEN"])
    path, eaten_at = plan(cells)
    if not eaten_at:
        raise SystemExit("Nenhuma contribuição no último ano: nada para a cobrinha comer.")
    os.makedirs(out_dir, exist_ok=True)
    for name, theme in THEMES.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(render(cells, path, eaten_at, theme))
    print(f"{len(eaten_at)} blocos, {len(path) - 1} passos, ciclo de {(len(path) - 1) * STEP + PAUSE:.1f}s")


if __name__ == "__main__":
    main()
