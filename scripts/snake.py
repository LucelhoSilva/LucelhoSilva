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
STEP = 0.09          # segundos por casa
SPACING = STEP / 2   # dois gomos por casa: o corpo fica contínuo
START_LEN = 3        # casas ocupadas no início
MAX_LEN = 28         # casas ocupadas depois de comer o último bloco
PAUSE = 1.5          # segundos com o tabuleiro vazio antes de recomeçar
ENTRY_ROW = 3        # linha por onde a cobrinha entra

# Projeção 3D: colunas para a direita, linhas recuando para trás (direita e para cima), altura para cima
ROWS = 7
CW = 15.0                     # largura de uma coluna (px)
DX, DY = 6.0, 12.0            # recuo de cada linha
GAP = 0.12                    # folga entre blocos (fração da casa)
HEIGHTS = [2, 6, 10, 14, 19]  # altura por nível; 0 é a lajota vazia
SNAKE_Z = 8                   # altura do centro da cobrinha acima do chão

THEMES = {
    "github-snake.svg": {
        "id": "l", "empty": "#ebedf0", "levels": ["#9be9a8", "#40c463", "#30a14e", "#216e39"],
        "head": "#7C3AED", "tail": "#A78BFA", "pupil": "#1f2328", "shadow": 0.18,
    },
    "github-snake-dark.svg": {
        "id": "d", "empty": "#21262d", "levels": ["#0e4429", "#006d32", "#26a641", "#39d353"],
        "head": "#C084FC", "tail": "#7C3AED", "pupil": "#0d1117", "shadow": 0.45,
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


def block(level, top):
    """Bloco em coordenadas locais, com origem no canto frontal esquerdo da base.

    Luz vindo de cima e da esquerda: topo claro, frente média e lateral direita mais escura.
    """
    size, h = 1 - 2 * GAP, HEIGHTS[level]
    offset = lambda du, dv, z: (du * CW - dv * DX, dv * DY - z)
    face = lambda pts, fill: '<polygon points="%s" fill="%s"/>' % (" ".join("%.1f,%.1f" % offset(*p) for p in pts), fill)
    return (face([(0, 0, 0), (size, 0, 0), (size, 0, h), (0, 0, h)], shade(top, 0.8))
            + face([(size, 0, 0), (size, -size, 0), (size, -size, h), (size, 0, h)], shade(top, 0.64))
            + face([(0, 0, h), (size, 0, h), (size, -size, h), (0, -size, h)], top))


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
    shadows, body = [], []
    for j in range(gomos - 1, -1, -1):  # da cauda para a cabeça, para a cabeça ficar por cima
        k = j / (gomos - 1)
        radius = 8.0 if j == 0 else 6.6 - 2.2 * k
        delay = j * SPACING
        show = appear(j, delay)
        shadows.append(
            f'<ellipse rx="{radius * 1.1:.1f}" ry="{radius * 0.5:.1f}" fill="#000000" fill-opacity="{theme["shadow"]}" '
            f'opacity="0">{motion(delay, "shadow")}{show}</ellipse>'
        )
        if j:
            body.append(
                f'<g opacity="0"><circle r="{radius:.1f}" fill="{mix(theme["head"], theme["tail"], k)}"/>'
                f'<circle r="{radius:.1f}" fill="url(#{p}shine)"/>{motion(delay)}{show}</g>'
            )
    head = (
        f'<g opacity="0"><circle r="8" fill="{theme["head"]}"/><circle r="8" fill="url(#{p}shine)"/>{motion(0)}{appear(0, 0)}</g>'
        f'<g opacity="0"><circle cx="3.1" cy="-3.4" r="2.5" fill="#ffffff"/><circle cx="3.1" cy="3.4" r="2.5" fill="#ffffff"/>'
        f'<circle cx="4" cy="-3.4" r="1.25" fill="{theme["pupil"]}"/><circle cx="4" cy="3.4" r="1.25" fill="{theme["pupil"]}"/>'
        f'<circle cx="3.4" cy="-4.1" r="0.6" fill="#ffffff"/><circle cx="3.4" cy="2.7" r="0.6" fill="#ffffff"/>'
        f'{motion(0, rotate=True)}{appear(0, 0)}</g>'
    )

    left, right = -12, columns * CW + ROWS * DX + 12
    top, bottom = -(HEIGHTS[-1] + 16), ROWS * DY + 10
    defs = (
        f'<radialGradient id="{p}shine" cx="0.35" cy="0.3" r="0.75">'
        '<stop offset="0" stop-color="#ffffff" stop-opacity="0.65"/><stop offset="0.35" stop-color="#ffffff" stop-opacity="0.12"/>'
        '<stop offset="1" stop-color="#000000" stop-opacity="0.3"/></radialGradient>'
        f'<g id="{p}t">{block(0, theme["empty"])}</g>'
        + "".join(f'<g id="{p}b{level}">{block(level, color)}</g>' for level, color in enumerate(theme["levels"], start=1))
        + f'<path id="{p}route" d="{route_path(path, SNAKE_Z)}"/><path id="{p}shadow" d="{route_path(path, 0)}"/>'
    )
    title = "Cobrinha 3D comendo o gráfico de contribuições"
    desc = f"A cobrinha percorre {len(eaten_at)} dias com contribuições do último ano e cresce de {START_LEN} para {MAX_LEN} casas."
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="{left} {top} {right - left:.0f} {bottom - top:.0f}" width="{right - left:.0f}" height="{bottom - top:.0f}" '
        f'role="img" aria-labelledby="{p}title {p}desc"><title id="{p}title">{escape(title)}</title><desc id="{p}desc">{escape(desc)}</desc>'
        f'<defs>{defs}</defs><g>{"".join(tiles)}</g><g>{"".join(blocks)}</g>'
        f'<g>{"".join(shadows)}</g><g>{"".join(body)}{head}</g></svg>\n'
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
