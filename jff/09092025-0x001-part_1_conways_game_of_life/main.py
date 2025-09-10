import os
from time import sleep
from random import randint


def print_world(world):
    str_world = ""
    for r in world:
        for c in r:
            if c:
                str_world += "O"
            else:
                str_world += "."
        str_world += "\n"

    print(str_world)


def get_neighbors(row_index, column_index, world):
    row_ct = len(world)
    column_ct = len(world[0])
    neighbors = []

    for ri in range(row_index - 1, row_index + 2):
        for ci in range(column_index - 1, column_index + 2):
            if (
                ri > -1
                and ci > -1
                and ri < row_ct
                and ci < column_ct
                and (ri, ci) != (row_index, column_index)
            ):
                neighbors.append(world[ri][ci])
    return neighbors


world = []

rows = 24
columns = 80

for _ in range(0, rows):
    world.append([])
    for __ in range(0, columns):
        world[-1].append(randint(0, 100) <= 15)

print_world(world)

while True:
    nwo = []
    os.system("clear")
    print_world(world)
    for ri, r in enumerate(world):
        nwo.append([])
        for ci, c in enumerate(r):
            neighbors = get_neighbors(ri, ci, world)
            neighbor_living_count = neighbors.count(True)

            if neighbor_living_count < 2:
                # Any live cell with fewer than two live neighbors dies, as if by underpopulation.
                nwo[-1].append(False)
            elif neighbor_living_count == 3:
                # Any dead cell with exactly three live neighbors becomes a live cell, as if by reproduction.
                nwo[-1].append(True)
            elif neighbor_living_count == 2:
                # Any live cell with two or three live neighbors lives on to the next generation.
                nwo[-1].append(world[ri][ci])
            elif neighbor_living_count > 3:
                # Any live cell with more than three live neighbors dies, as if by overpopulation.
                nwo[-1].append(False)
    world = nwo
    sleep(0.1)
