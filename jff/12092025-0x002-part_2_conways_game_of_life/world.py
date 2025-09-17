from random import randint


class World(object):
    def __init__(self, rows=24, columns=80, density=15):
        self.world = []

        self.rows = rows
        self.columns = columns

        for _ in range(0, rows):
            self.world.append([])
            for __ in range(0, columns):
                self.world[-1].append(randint(0, 100) <= density)

    def __str__(self):
        str_world = ""
        for r in self.world:
            for c in r:
                str_world += "O" if c else "."
            str_world += "\n"

        return str_world

    def _get_neighbors(self, row_i, column_i):
        neighbors = []

        for ri in range(row_i - 1, row_i + 2):
            for ci in range(column_i - 1, column_i + 2):
                if (ri, ci) != (row_i, column_i):
                    ri = ri % self.rows
                    ci = ci % self.columns
                    neighbors.append(self.world[ri][ci])

        return neighbors

    def __call__(self):
        nwo = []
        for ri, r in enumerate(self.world):
            nwo.append([])
            for ci, c in enumerate(r):
                neighbors = self._get_neighbors(ri, ci)
                neighbor_living_count = neighbors.count(True)

                if neighbor_living_count < 2:
                    # Any live cell with fewer than two live neighbors dies, as if by underpopulation.
                    nwo[-1].append(False)
                elif neighbor_living_count == 3:
                    # Any dead cell with exactly three live neighbors becomes a live cell, as if by reproduction.
                    nwo[-1].append(True)
                elif neighbor_living_count == 2:
                    # Any live cell with two or three live neighbors lives on to the next generation.
                    nwo[-1].append(self.world[ri][ci])
                elif neighbor_living_count > 3:
                    # Any live cell with more than three live neighbors dies, as if by overpopulation.
                    nwo[-1].append(False)
        self.world = nwo
