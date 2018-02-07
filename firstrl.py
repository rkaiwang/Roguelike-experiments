import libtcodpy as libtcod
import os
import math

# So in Python, if variables are capitalised then they become GLOBAL VARIABLES

SCREEN_WIDTH = 80   # initialise screen variables, actual size of the window
SCREEN_HEIGHT = 50
LIMIT_FPS = 20 # 20 frames-per-second maximum

# The map is a 2-d array of tiles that the character moves around
MAP_WIDTH = 80
MAP_HEIGHT = 45

ROOM_MAX_SIZE = 10
ROOM_MIN_SIZE = 6
MAX_ROOMS = 30
MAX_ROOM_MONSTERS = 3

FOV_ALGO = 0  # default FOV algorithm
FOV_LIGHT_WALLS = True
TORCH_RADIUS = 10


# We have 2 tile types - wall and ground.
# These will be their "dark" colors, which you'll see when they're not in FOV;
# their "lit" counterparts are not needed right now. Notice that their values are
# between 0 and 255, they are RBG values
color_dark_wall = libtcod.Color(0, 0, 100)
color_light_wall = libtcod.Color(130, 110, 50)
color_dark_ground = libtcod.Color(50, 50, 150)
color_light_ground = libtcod.Color(200, 180, 50)

class Rect:
    #a rectangle on the map, used to characterise a room (helps to build rectangular rooms
    def __init__(self, x, y, w, h):
        self.x1 = x  #x1 and y1 represent top left side of rectangle, whereas x2 an y2 represent bottom right of rectangle
        self.y1 = y
        self.x2 = x + w
        self.y2 = y + h

    def center(self): #used to find the centre of rooms, which is used to make tunnels
        center_x = (self.x1 + self.x2) // 2
        center_y = (self.y1 + self.y2) // 2
        return (center_x, center_y)

    def intersect(self, other):
        # returns true if this rectangle intersects with another one
        return (self.x1 <= other.x2 and self.x2 >= other.x1 and
                self.y1 <= other.y2 and self.y2 >= other.y1)

class Tile:
    # a tile of the map and its properties. We want to decide if a tile will physically block the player character
    # aka whether it is passable or not
    def __init__(self, blocked, block_sight=None):
        self.blocked = blocked

        # by default, if a tile is blocked, it also blocks sight
        block_sight = blocked if block_sight is None else None
        self.block_sight = block_sight

        self.explored = False

class Object:
    # this is a generic object: the player, a monster, an item, the stairs...
    # it's always represented by a character on screen.
    def __init__(self, x, y, char, name, color, blocks=False, fighter = None, ai = None):
        self.x = x
        self.y = y
        self.char = char
        self.color = color
        self.name = name
        self.blocks = blocks
        self.fighter = fighter
        if self.fighter: # let the fighter component know who owns it, only happens if the component is actually defined
            self.fighter.owner = self # the object sets the component's owner property to itself
        self.ai = ai
        if self.ai: # let the AI component know who owns it
            self.ai.owner = self

    def move(self, dx, dy):
        # move by the given amount, if the destination is not blocked
        if not is_blocked(self.x + dx, self.y + dy): #if statement here to stop movement if tile is not passable
            self.x += dx
            self.y += dy

    def move_towards(self, target_x, target_y):
        # vector from this object to the target, and distance
        dx = target_x - self.x
        dy = target_y - self.y
        distance = math.sqrt(dx ** 2 + dy ** 2)

        # normalise it to length 1 (preserving direction), then round it and
        # convert to integer so the movement is restricted to the map grid
        dx = int(round(dx / distance))
        dy = int(round(dy /distance))

        self.move(dx, dy)

    def distance_to(self, other):
        # return the distance to another object
        dx = other.x - self.x
        dy = other.y - self.y
        return math.sqrt(dx ** 2 + dy ** 2)

    def draw(self):
        #only show if it's visible to the player
        if libtcod.map_is_in_fov(fov_map, self.x, self.y):
            #set the color and then draw the character that represents this object at its position
            libtcod.console_set_default_foreground(con, self.color)
            libtcod.console_put_char(con, self.x, self.y, self.char, libtcod.BKGND_NONE)

    def clear(self):
        # erase the character that represents this object
        libtcod.console_put_char(con, self.x, self.y, ' ', libtcod.BKGND_NONE)

# So we use composition to separate different types of objects
# A component class defines extra properties and methods for an object that needs them
# Then you slap on an instance of the component class as a property of the object
# It now owns the component
class Fighter:
    # combat-related properties and methods (monster, player, NPC)
    def __init__(self, hp, defense, power, death_function=None):
        self.max_hp = hp
        self.hp = hp
        self.defense = defense
        self.power = power
        self.death_function = death_function

    def take_damage(self, damage):
        # apply damage if possible
        if damage > 0:
            self.hp -= damage
        # check for death. if there's a death function, call it
        if self.hp <= 0:
            function = self.death_function
            if function is not None:
                function(self.owner)

    def attack(self, target):
        # a simple formula for attack damage
        damage = self.power - target.fighter.defense
        if damage > 0:
            # make the target take some damage
            print(self.owner.name.capitalize() + ' attacks ' + target.name + ' for ' + str(damage) + ' hitpoints.')
            target.fighter.take_damage(damage)
        else:
            print(self.owner.name.capitalize() + ' attacks ' + target.name + ' but it has no effect!')

class BasicMonster:
    # AI for a basic monster
    def take_turn(self):
        # a basic monster takes its turn. If you can see it, it can see you
        monster = self.owner
        if libtcod.map_is_in_fov(fov_map, monster.x, monster.y):

            # move towards player if far away
            if monster.distance_to(player) >= 2:
                monster.move_towards(player.x, player.y)

            # close enough, attack! (if he player is still alive)
            elif player.fighter.hp > 0:
                monster.fighter.attack(player)


def is_blocked(x, y):
    # first test the map tile
    if map[x][y].blocked:
        return True

    # now check for any blocking objects
    for object in objects:
        if object.blocks and object.x == x and object.y == y:
            return True

    return False

def make_map():
    # Dungeon generator. Basic concept is pick a random location for the first room and carve it.
    # Then pick another location for the second, which doesn't overlap with the first room
    # Connect the two with a tunnel and repeat. This will yield a sequence of connected rooms.
    # The downside of this is that there will be lots of overlaps between the tunnels, and even
    # tunnels overlapping rooms

    global map

    # fill map with "blocked" tiles
    map = [
        [Tile(True) for y in range(MAP_HEIGHT)] #creates tiles to put into map, false meaning that they do not block
        for x in range(MAP_WIDTH)
    ]

    rooms = []
    num_rooms = 0

    for r in range(MAX_ROOMS):
        # random width and height
        w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE) #this function returns a random integer between two numbers
        h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
        # random position without going out of the boundaries of the map
        x = libtcod.random_get_int(0, 0, MAP_WIDTH - w - 1)
        y = libtcod.random_get_int(0, 0, MAP_HEIGHT - h - 1)

        # "Rect" class makes rectangles easier to work with
        new_room = Rect(x, y, w, h)

        # add some contents to this room, such as monsters
        place_objects(new_room)

        # run through the other rooms and see if they intersect with this one
        failed = False
        for other_room in rooms:
            if new_room.intersect(other_room):
                failed = True
                break

        if not failed:
            # this means there are no intersections, so this room is valid

            # "paint" it to the map's tiles
            create_room(new_room)

            # center coordinates of new room, will be useful later
            (new_x, new_y) = new_room.center()

            # optional: print "room number" to see how the map drawing worked
            #          we may have more than ten rooms, so print 'A' for the first room, 'B' for the next...
            # room_no = Object(new_x, new_y, chr(65+num_rooms), 'room number', libtcod.white)
            # objects.insert(0, room_no) #draw early, so monsters are drawn on top

            if num_rooms == 0:
                # this is the first room, where the player starts at
                player.x = new_x
                player.y = new_y

            else:
                # all rooms after the first:
                # connect it to the previous room with a tunnel

                # center coordinates of previous room
                (prev_x, prev_y) = rooms[num_rooms - 1].center()

                # draw a coin (random number that is either 0 or 1)
                if libtcod.random_get_int(0, 0, 1) == 1:
                    # first move horizontally, then vertically
                    create_h_tunnel(prev_x, new_x, prev_y)
                    create_v_tunnel(prev_y, new_y, new_x)
                else:
                    # first move vertically, then horizontally
                    create_v_tunnel(prev_y, new_y, prev_x)
                    create_h_tunnel(prev_x, new_x, new_y)

            # finally, append the new room to the list
            rooms.append(new_room)
            num_rooms += 1

def place_objects(room):
    # choose random number of monsters
    num_monsters = libtcod.random_get_int(0, 0, MAX_ROOM_MONSTERS)

    for i in range(num_monsters):
        #choose random spot for this monster
        x = libtcod.random_get_int(0, room.x1, room.x2)
        y = libtcod.random_get_int(0, room.y1, room.y2)

        #only place it if the tile is not blocked
        if not is_blocked(x, y):
            choice = libtcod.random_get_int(0, 0, 100)
            if choice < 20:
                # create a bat
                fighter_component = Fighter(hp=4, defense=1, power=1)
                ai_component = BasicMonster()

                monster = Object(x, y, 'w', 'bat', libtcod.light_yellow, blocks=True, fighter=fighter_component, ai=ai_component)

            elif choice < 20 + 40:
                # create a troll
                fighter_component = Fighter(hp=12, defense=1, power=4)
                ai_component = BasicMonster()

                monster = Object(x, y, 'T', 'troll', libtcod.dark_violet, blocks=True, fighter=fighter_component, ai=ai_component)

            else:
                # create a zombie
                fighter_component = Fighter(hp=5, defense=0, power=3)
                ai_component = BasicMonster()

                monster = Object(x, y, 'Z', 'zombie', libtcod.desaturated_green, blocks=True, fighter=fighter_component, ai=ai_component)

            objects.append(monster)

def render_all(): #this is called in the main loop

    global fov_map, color_dark_wall, color_light_wall
    global color_dark_ground, color_light_ground
    global fov_recompute

    if fov_recompute:
        # recompute FOV if needed (the player moved or something)
        fov_recompute = False
        libtcod.map_compute_fov(fov_map, player.x, player.y, TORCH_RADIUS, FOV_LIGHT_WALLS, FOV_ALGO)

        for y in range(MAP_HEIGHT):
            for x in range(MAP_WIDTH):
                visible = libtcod.map_is_in_fov(fov_map, x, y)
                wall = map[x][y].block_sight
                if not visible:
                    #it's out of the player's FOV
                    #if it's not visible right now, the player can only see it if it's explored
                    if map[x][y].explored:
                        if wall:
                            libtcod.console_set_char_background(con, x, y, color_dark_wall, libtcod.BKGND_SET)
                        else:
                            libtcod.console_set_char_background(con, x, y, color_dark_ground, libtcod.BKGND_SET)
                else:
                    #it's visible
                    if wall:
                        libtcod.console_set_char_background(con, x, y, color_light_wall, libtcod.BKGND_SET )
                    else:
                        libtcod.console_set_char_background(con, x, y, color_light_ground, libtcod.BKGND_SET )
                    #since it's visible, explore it
                    map[x][y].explored = True

    # draw all objects in the list
    for object in objects:
        object.draw()

    # blit the contents of "con" to the root console and present it
    libtcod.console_blit(con, 0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, 0, 0)

def player_move_or_attack(dx, dy):
    global fov_recompute

    # the co-ordinates the player is moving to/attacking
    x = player.x + dx
    y = player.y + dy

    # try to find an attackable object there
    target = None
    for object in objects:
        if object.x == x and object.y == y:
            target = object
            break

    # attack if target found, move otherwise
    if target is not None:
        player.fighter.attack(target)
    else:
        player.move(dx, dy)
        fov_recompute = True

def handle_keys():

    global fov_recompute
    global game_state
    global player_action

    key = libtcod.console_wait_for_keypress(True) #turn-based movement
    if key.vk == libtcod.KEY_ENTER and key.lalt:
        #Alt+Enter: toggle fullscreen
        libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())

    elif key.vk == libtcod.KEY_ESCAPE:
        return 'exit'  #exit game

    if game_state == 'playing': # marker used to differentiate between like pausing so that you can't move while paused or dead char
        # movement keys
        if libtcod.console_is_key_pressed(libtcod.KEY_UP):
            player_move_or_attack(0, -1)

        elif libtcod.console_is_key_pressed(libtcod.KEY_DOWN):
            player_move_or_attack(0, 1)

        elif libtcod.console_is_key_pressed(libtcod.KEY_LEFT):
            player_move_or_attack(-1, 0)

        elif libtcod.console_is_key_pressed(libtcod.KEY_RIGHT):
            player_move_or_attack(1, 0)
        else:
            return 'didnt-take-turn'

def create_room(room):
    global map
    #go through the tiles in the rectangle and make them passable
    for x in range(room.x1 + 1, room.x2): #the +1 is used so that we leave one tile out on each side of the room so we can place a wall
        for y in range(room.y1 + 1, room.y2):
            map[x][y].blocked = False
            map[x][y].block_sight = False

def create_h_tunnel(x1, x2, y): #carves horizontal tunnel
    global map
    for x in range(min(x1, x2), max(x1, x2) + 1): #the min and max functions are useful, since it means no matter if x1 > x2 or x2> x1, they will always be compatible with the range function
        map[x][y].blocked = False
        map[x][y].block_sight = False

def create_v_tunnel(y1, y2, x):
    global map
    #vertical tunnel
    for y in range(min(y1, y2), max(y1, y2) + 1):
        map[x][y].blocked = False
        map[x][y].block_sight = False

def player_death(player):
    # the game ended!
    global game_state
    print('You died!')
    game_state = 'dead'

    # for added effect, transform the player into a corpse!
    player.char = '%'
    player.color = libtcod.dark_red

def monster_death(monster):
    # transform it into a nasty corpse! It doesn't block, can't be
    # attacked and doesn't move
    print(monster.name.capitalize() + ' is dead!')
    monster.char = '%'
    monster.color = libtcod.dark_red
    monster.blocks = False
    monster.fighter = None # so you can change class attributes to None
    monster.ai = None
    monster.name = 'remains of ' + monster.name # so doing this diables the monster's components so
    # it doesn't run any AI functions and can't be attacked



#############################################
# Initialization & Main Loop
#############################################

cwd_path = os.path.dirname(os.path.realpath(__file__))
data_path = os.path.abspath(os.path.join(cwd_path, 'data'))
font = os.path.join(data_path, 'fonts', 'consolas10x10_gs_tc.png')
libtcod.console_set_custom_font(font, libtcod.FONT_TYPE_GREYSCALE | libtcod.FONT_LAYOUT_TCOD)
libtcod.console_init_root(SCREEN_WIDTH, SCREEN_HEIGHT, 'python/libtcod tutorial', False)
libtcod.sys_set_fps(LIMIT_FPS)
con = libtcod.console_new(SCREEN_WIDTH, SCREEN_HEIGHT)

# create object representing the player
fighter_component = Fighter(hp=30, defense=2, power=5)
player = Object(0, 0, '@', 'player', libtcod.white, blocks=True, fighter=fighter_component)

# create an NPC
# npc = Object(SCREEN_WIDTH // 2 - 5, SCREEN_HEIGHT // 2, '@', libtcod.yellow)

# the list of objects with those two
objects = [player] # objects = [npc, player] if there is an NPC

#generate map (at this point it's not drawn to the screen)
make_map()

fov_map = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
for y in range(MAP_HEIGHT):
    for x in range(MAP_WIDTH):
        libtcod.map_set_properties(fov_map, x, y, not map[x][y].block_sight, not map[x][y].blocked)

fov_recompute = True
game_state = 'playing'
player_action = None

while not libtcod.console_is_window_closed():

    #render the screen
    render_all()

    libtcod.console_flush()

    # erase all objects at their old locations, before they move
    for object in objects:
        object.clear()

    # handle keys and exit game if needed
    player_action = handle_keys()
    if player_action == 'exit':
        break

    #let monsters take their turn
    if game_state == 'playing' and player_action != 'didnt-take-turn':
        for object in objects:
            if object.ai:
                object.ai.take_turn()

    #show the player's stats
    libtcod.console_set_default_foreground(con, libtcod.white)
    libtcod.console_print_ex(con, 1, SCREEN_HEIGHT - 2, libtcod.BKGND_NONE, libtcod.LEFT,
        'HP: ' + str(player.fighter.hp) + '/' + str(player.fighter.max_hp))







