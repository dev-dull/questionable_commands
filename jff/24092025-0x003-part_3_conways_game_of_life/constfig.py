import argparse
from sys import exit
from random import randint


class _C(object):
    # C stands for "CONSTANT" and that's good enough for me.
    def __init__(self):
        parser = argparse.ArgumentParser(description="Conway's Game of Life")
        parser.add_argument(
            "-r",
            "--rows",
            type=int,
            default=24,
            help="The number of rows in the critter world.",
        )
        parser.add_argument(
            "-c",
            "--columns",
            type=int,
            default=80,
            help="The number of columns in the critter world.",
        )
        parser.add_argument(
            "-d",
            "--density",
            type=int,
            default=10,
            help="The likelihood of any given point being populated with a living critter.",
        )
        parser.add_argument(
            "-m",
            "--mutation",
            type=float,
            default=0.01,
            help="The amount of mutation for a new critter.",
        )
        parser.add_argument(
            "-b",
            "--bad-mutation",
            type=int,
            default=0,
            help="Increases the chance a mutation will be unfavorable.",
        )
        self._arguments = parser.parse_args()

        self.ROWS = self._arguments.rows
        self.COLUMNS = self._arguments.columns
        self.DENSITY = self._arguments.density
        self.MUTATION = self._arguments.mutation
        self.BAD_MUTATION = self._arguments.bad_mutation

        try:
            self.validate_arguments()
        except AssertionError as e:
            print(e)
            exit(1)

        self._set_constants()

    def _set_constants(self):
        self.KEYWORD_UNDERPOPULATION_VALUE = "underpopulation_value"
        self.KEYWORD_MIN_SURVIVE_VALUE = "min_survive_value"
        self.KEYWORD_MAX_SURVIVE_VALUE = "max_survive_value"
        self.KEYWORD_MIN_SPAWN_VALUE = "min_spawn_value"
        self.KEYWORD_MAX_SPAWN_VALUE = "max_spawn_value"
        self.KEYWORD_OVERPOPULATION_VALUE = "overpopulation_value"
        self.KEYWORD_CRITTER_ARGUMENTS = [
            self.KEYWORD_UNDERPOPULATION_VALUE,
            self.KEYWORD_MIN_SURVIVE_VALUE,
            self.KEYWORD_MAX_SURVIVE_VALUE,
            self.KEYWORD_MIN_SPAWN_VALUE,
            self.KEYWORD_MAX_SPAWN_VALUE,
            self.KEYWORD_OVERPOPULATION_VALUE,
        ]

        self.DEFAULT_CRITTER_VALUES = {
            self.KEYWORD_UNDERPOPULATION_VALUE: 2.0,
            self.KEYWORD_MIN_SURVIVE_VALUE: 2.0,
            self.KEYWORD_MAX_SURVIVE_VALUE: 3.0,
            self.KEYWORD_MIN_SPAWN_VALUE: 3.0,
            self.KEYWORD_MAX_SPAWN_VALUE: 3.0,
            self.KEYWORD_OVERPOPULATION_VALUE: 3.0,
        }

        _increase = (
            lambda v: v + (randint(self.BAD_MUTATION, 100) * self.MUTATION) / 100
        )
        _decrease = (
            lambda v: v - (randint(self.BAD_MUTATION, 100) * self.MUTATION) / 100
        )

        self.CRITTER_MUTATORS = {
            self.KEYWORD_UNDERPOPULATION_VALUE: _decrease,  # Tolerate fewer neighbors (-=)
            self.KEYWORD_MIN_SURVIVE_VALUE: _decrease,  # Needs fewer neighbors to survive (-=)
            self.KEYWORD_MAX_SURVIVE_VALUE: _increase,  # Tolerate more neighbors (+=)
            self.KEYWORD_MIN_SPAWN_VALUE: _decrease,  # Spawn new critter with fewer partners (-=)
            self.KEYWORD_MAX_SPAWN_VALUE: _increase,  # Spawn new critter with more partners (+=)
            self.KEYWORD_OVERPOPULATION_VALUE: _increase,  # Better tolerate overpopulation (+=)
        }

    def validate_arguments(self):
        assert (
            self.DENSITY <= 100
        ), "--density is a percentage and should not exceed 100."
        assert (
            0 <= self.MUTATION < 1
        ), "--mutation should be a number between 0 (zero) and 1."
        assert (
            -100 <= self.BAD_MUTATION <= 0
        ), "--bad-mutation should be a number between 0 (zero) and 100."


C = _C()
