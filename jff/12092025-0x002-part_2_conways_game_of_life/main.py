from os import system
from time import sleep
from world import World


def main():
    world = World(rows=30, columns=100, density=8)
    while True:
        system("clear")
        print(world)
        world()
        sleep(0.1)


if __name__ == "__main__":
    main()
