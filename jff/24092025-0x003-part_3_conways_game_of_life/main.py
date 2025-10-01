from constfig import C
from time import sleep
from world import World


def main():
    world = World(rows=C.ROWS, columns=C.COLUMNS, density=C.DENSITY)
    try:
        while True:
            print(world)
            world()
            sleep(0.1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
