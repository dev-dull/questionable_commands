from constfig import C


class Critter(object):
    def __init__(self, alive, **kwargs):
        self.alive = alive

        for k, v in kwargs.items():
            setattr(self, k, C.CRITTER_MUTATORS[k](v))

    def __bool__(self):
        return self.alive

    def __str__(self):
        return "O" if self.alive else "."
