import pygame
from pygame.locals import *
from OpenGL.GL import *
from OpenGL.GLU import *
import math

WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600
GRID_SIZE = 10
BLOCK_SIZE = 1.0
FOV_Y = 45.0  # vertical field of view in degrees

blocks = set()  # set of (gx, gz) cells that have a block

camera = {
    "yaw": 45.0,
    "pitch": 30.0,
    "distance": 15.0,
}

mouse_down = False
last_mouse_pos = (0, 0)
hover_cell = None  # (gx, gz) currently under the mouse


# ---------- geometry helpers ----------

def camera_basis():
    """Return (eye, forward, right, up) for the current camera orbit."""
    yaw = math.radians(camera["yaw"])
    pitch = math.radians(camera["pitch"])
    d = camera["distance"]

    eye = (
        d * math.cos(pitch) * math.sin(yaw),
        d * math.sin(pitch),
        d * math.cos(pitch) * math.cos(yaw),
    )
    target = (0.0, 0.0, 0.0)
    world_up = (0.0, 1.0, 0.0)

    # forward = normalize(target - eye)
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    fz = target[2] - eye[2]
    flen = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    forward = (fx / flen, fy / flen, fz / flen)

    # right = normalize(forward x world_up)
    rx = forward[1] * world_up[2] - forward[2] * world_up[1]
    ry = forward[2] * world_up[0] - forward[0] * world_up[2]
    rz = forward[0] * world_up[1] - forward[1] * world_up[0]
    rlen = math.sqrt(rx * rx + ry * ry + rz * rz) or 1.0
    right = (rx / rlen, ry / rlen, rz / rlen)

    # up = right x forward
    ux = right[1] * forward[2] - right[2] * forward[1]
    uy = right[2] * forward[0] - right[0] * forward[2]
    uz = right[0] * forward[1] - right[1] * forward[0]
    up = (ux, uy, uz)

    return eye, forward, right, up


def screen_to_grid(mouse_x, mouse_y):
    """Cast a ray from the camera through the pixel and hit the y=0 plane."""
    eye, forward, right, up = camera_basis()

    # Normalised device coords in [-1, 1], y flipped because pygame is top-down
    ndc_x = (2.0 * mouse_x / WINDOW_WIDTH) - 1.0
    ndc_y = 1.0 - (2.0 * mouse_y / WINDOW_HEIGHT)

    aspect = WINDOW_WIDTH / WINDOW_HEIGHT
    tan_half_fov = math.tan(math.radians(FOV_Y) / 2.0)

    # Ray direction in world space
    sx = forward[0] + ndc_x * tan_half_fov * aspect * right[0] + ndc_y * tan_half_fov * up[0]
    sy = forward[1] + ndc_x * tan_half_fov * aspect * right[1] + ndc_y * tan_half_fov * up[1]
    sz = forward[2] + ndc_x * tan_half_fov * aspect * right[2] + ndc_y * tan_half_fov * up[2]

    if abs(sy) < 1e-6:
        return None
    t = -eye[1] / sy
    if t < 0:
        return None

    hit_x = eye[0] + t * sx
    hit_z = eye[2] + t * sz

    half_grid = GRID_SIZE * BLOCK_SIZE / 2.0
    gx = int((hit_x + half_grid) / BLOCK_SIZE)
    gz = int((hit_z + half_grid) / BLOCK_SIZE)

    if 0 <= gx < GRID_SIZE and 0 <= gz < GRID_SIZE:
        return (gx, gz)
    return None


# ---------- rendering ----------

def draw_cube(x, y, z, size):
    half = size / 2.0
    vertices = [
        (x - half, y - half, z - half),
        (x + half, y - half, z - half),
        (x + half, y + half, z - half),
        (x - half, y + half, z - half),
        (x - half, y - half, z + half),
        (x + half, y - half, z + half),
        (x + half, y + half, z + half),
        (x - half, y + half, z + half),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (2, 3, 7, 6),
        (1, 2, 6, 5),
        (0, 3, 7, 4),
    ]
    glBegin(GL_QUADS)
    for i, face in enumerate(faces):
        if i == 0: glColor3f(0.8, 0.3, 0.3)
        elif i == 1: glColor3f(0.3, 0.8, 0.3)
        elif i == 2: glColor3f(0.3, 0.3, 0.8)
        elif i == 3: glColor3f(0.8, 0.8, 0.3)
        elif i == 4: glColor3f(0.8, 0.3, 0.8)
        else: glColor3f(0.3, 0.8, 0.8)
        for v in face:
            glVertex3fv(vertices[v])
    glEnd()

    glColor3f(0.0, 0.0, 0.0)
    glLineWidth(1.0)
    glBegin(GL_LINES)
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    for edge in edges:
        for v in edge:
            glVertex3fv(vertices[v])
    glEnd()


def draw_grid():
    glColor3f(0.5, 0.5, 0.5)
    glLineWidth(1.0)
    glBegin(GL_LINES)
    half_grid = GRID_SIZE * BLOCK_SIZE / 2.0
    for i in range(GRID_SIZE + 1):
        x = -half_grid + i * BLOCK_SIZE
        glVertex3f(x, 0, -half_grid)
        glVertex3f(x, 0, half_grid)
        z = -half_grid + i * BLOCK_SIZE
        glVertex3f(-half_grid, 0, z)
        glVertex3f(half_grid, 0, z)
    glEnd()


def draw_hover(gx, gz, existing):
    """Draw a marker for the cell under the mouse.
    Green outline if empty, red outline if occupied."""
    half_grid = GRID_SIZE * BLOCK_SIZE / 2.0
    cx = -half_grid + gx * BLOCK_SIZE + BLOCK_SIZE / 2.0
    cz = -half_grid + gz * BLOCK_SIZE + BLOCK_SIZE / 2.0

    if existing:
        glColor3f(1.0, 0.2, 0.2)
        y = BLOCK_SIZE + 0.01  # draw just above the cube
    else:
        glColor3f(0.2, 1.0, 0.2)
        y = 0.02

    glLineWidth(2.5)
    glBegin(GL_LINE_LOOP)
    h = BLOCK_SIZE / 2.0
    glVertex3f(cx - h, y, cz - h)
    glVertex3f(cx + h, y, cz - h)
    glVertex3f(cx + h, y, cz + h)
    glVertex3f(cx - h, y, cz + h)
    glEnd()
    glLineWidth(1.0)


# ---------- main loop ----------

def main():
    global mouse_down, last_mouse_pos, hover_cell

    pygame.init()
    pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("Crash Bandicoot Level Block Designer")

    glEnable(GL_DEPTH_TEST)
    glClearColor(0.2, 0.2, 0.3, 1.0)

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(FOV_Y, WINDOW_WIDTH / WINDOW_HEIGHT, 0.1, 100.0)
    glMatrixMode(GL_MODELVIEW)

    clock = pygame.time.Clock()
    running = True
    half_grid = GRID_SIZE * BLOCK_SIZE / 2.0

    while running:
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False

            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    running = False
                elif event.key == K_c:
                    blocks.clear()

            elif event.type == MOUSEBUTTONDOWN:
                if event.button == 1 and hover_cell:
                    # Left click: add if empty, otherwise ignore
                    if hover_cell not in blocks:
                        blocks.add(hover_cell)
                elif event.button == 3 and hover_cell:
                    # Right click: remove if present
                    if hover_cell in blocks:
                        blocks.remove(hover_cell)
                elif event.button == 2:
                    mouse_down = True
                    last_mouse_pos = event.pos

            elif event.type == MOUSEBUTTONUP:
                if event.button == 2:
                    mouse_down = False

            elif event.type == MOUSEMOTION:
                if mouse_down:
                    dx = event.pos[0] - last_mouse_pos[0]
                    dy = event.pos[1] - last_mouse_pos[1]
                    camera["yaw"] += dx * 0.5
                    camera["pitch"] += dy * 0.5
                    camera["pitch"] = max(-89.0, min(89.0, camera["pitch"]))
                    last_mouse_pos = event.pos

            elif event.type == MOUSEWHEEL:
                camera["distance"] -= event.y * 1.0
                camera["distance"] = max(5.0, min(50.0, camera["distance"]))

        # ---- Update hover from current mouse position ----
        mx, my = pygame.mouse.get_pos()
        hover_cell = screen_to_grid(mx, my)

        # ---- Render ----
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        eye, _, _, _ = camera_basis()
        gluLookAt(eye[0], eye[1], eye[2],
                  0.0, 0.0, 0.0,
                  0.0, 1.0, 0.0)

        draw_grid()

        for (gx, gz) in blocks:
            wx = -half_grid + gx * BLOCK_SIZE + BLOCK_SIZE / 2.0
            wz = -half_grid + gz * BLOCK_SIZE + BLOCK_SIZE / 2.0
            draw_cube(wx, 0.0, wz, BLOCK_SIZE)

        if hover_cell:
            draw_hover(hover_cell[0], hover_cell[1], hover_cell in blocks)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()