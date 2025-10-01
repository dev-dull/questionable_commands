from constfig import C
from random import randint
from critter import Critter
from collections import defaultdict


class World(object):
    def __init__(self, rows=24, columns=80, density=15):
        self.world = []

        self.rows = rows
        self.columns = columns

        for _ in range(0, rows):
            self.world.append([])
            for __ in range(0, columns):
                alive = randint(0, 100) <= density
                self.world[-1].append(Critter(alive, **C.DEFAULT_CRITTER_VALUES))

    def __str__(self):
        str_world = ""
        for r in self.world:
            for c in r:
                str_world += str(c)
            str_world += "\n"

        return f"{str_world}\033[{self.rows+1}A"

    def _get_neighbors(self, row_i, column_i):
        neighbors = []

        for ri in range(row_i - 1, row_i + 2):
            for ci in range(column_i - 1, column_i + 2):
                if (ri, ci) != (row_i, column_i):
                    ri = ri % self.rows
                    ci = ci % self.columns

                    if self.world[ri][ci]:
                        neighbors.append(self.world[ri][ci])

        return neighbors, len(neighbors)

    def _calculate_critter_averages(self, critters, neighbor_alive_count):
        averages = defaultdict(float)
        for critter in critters:
            for property in C.KEYWORD_CRITTER_ARGUMENTS:
                averages[property] += getattr(critter, property)

        for k, v in averages.items():
            averages[k] = v / neighbor_alive_count

        return averages

    def __call__(self):
        nwo = []
        for ri, r in enumerate(self.world):
            nwo.append([])
            for ci, c in enumerate(r):
                neighbors, neighbor_alive_count = self._get_neighbors(ri, ci)
                next_critter = None

                if neighbor_alive_count < c.underpopulation_value:
                    # Any live cell with fewer than two live neighbors dies, as if by underpopulation.
                    next_critter = Critter(False, **C.DEFAULT_CRITTER_VALUES)
                elif (
                    not c
                ) and c.min_spawn_value <= neighbor_alive_count <= c.max_spawn_value:
                    # Any dead cell with exactly three live neighbors becomes a live cell, as if by reproduction.
                    new_critter_values = self._calculate_critter_averages(
                        neighbors, neighbor_alive_count
                    )
                    next_critter = Critter(True, **new_critter_values)
                elif c.min_survive_value <= neighbor_alive_count <= c.max_survive_value:
                    # Any live cell with two or three live neighbors lives on to the next generation.
                    next_critter = c
                elif neighbor_alive_count > c.overpopulation_value:
                    # Any live cell with more than three live neighbors dies, as if by overpopulation.
                    next_critter = Critter(False, **C.DEFAULT_CRITTER_VALUES)
                else:
                    next_critter = c

                nwo[-1].append(next_critter)
        self.world = nwo
