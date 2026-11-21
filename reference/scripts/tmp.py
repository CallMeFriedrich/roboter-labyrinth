# connect robot ethernet to PC, power on robot
# PC: fixed IP 192.168.0.100/24 (robot has 192.168.0.30/24)

# method 1:
# set robot to manual mode (hardware key switch on mainboard)
# press and hold(!) the key on the right side of the touchpanel (Freigabe)
# press ABB on touchscreen (top left)
# press production (bottom left)
# press AP->main and confirm
# press play button (hardware-button on touch panel)
# on PC: python3 test.py
# (if the Freigabe key is released, interrupt python script (ctrl+c), press AP->main again and confirm, press the play button)

# method 2:
# set robot to automatic mode (hardware key switch on mainboard)
# switch motors on: press the hardware button near the power switch (on mainboard) (there should be written motors on). 
# press ABB on touchscreen (top left)
# press production (bottom left)
# press AP->main and confirm
# press play button (hardware-button on touch panel)
# on PC: python3 test.py

# https://github.com/robotics/open_abb

import math, time

import abb
R = abb.Robot()

R.set_speed([75,75,5,5]) # speed: [robot TCP linear speed (mm/s), TCP orientation speed (deg/s), external axis linear, external axis orientation]

#print(R.get_cartesian())

# R.set_cartesian([[X,Y,Z], [Quaternions]]) XYT in mm, quaternions: [0,0,1,0] is "tool down", [1,0,0,0] is "tool up"

#R.set_joints([0.,0.,0.,0.,0.,0.]);

#R.set_joints([45.,0.,0.,0.,0.,0.]);

#R.set_joints([45.,30.,0.,0.,0.,0.]);

#R.set_joints([0.,0.,0.,0.,0.,0.]);

#R.set_joints([0.,45.,0.,0.,40.,0.]);


#R.set_joints([0.,0.,0.,0.,0.,0.]);
#R.set_joints([0.,0.,0.,0.,0.,105.]);

#print(R.get_cartesian())

# use https://quaternions.online/ to visualize quaternions (simulation x is tool up)

#R.set_tool([[20,0,-150], [0,0,1,0]])
R.set_tool()

#print(R.get_cartesian())

#R.set_cartesian([[224.0+30, 19.32, 635.18-200], [0.43, 0.561, -0.43, -0.561]])

R.set_joints([0.,45.,0.,0.,-45.,0]);
#print(R.get_cartesian())

print(R.get_cartesian())


base_coordinates = [420, 0, 322.05-85]
new_base = [420, 200, 322.05-75] #120 420
base_orientation = [0.707, 0.0, 0.707, 0.0] #[0.5, -0.5, 0.5, -0.5] # [0.43, 0.561, -0.43, -0.561] # [0.5, 0.5, 0.5, 0.5]
var_coordinates = [560, 200, 322.05-60]#[375.96, 19.32, 322.05]
coordinates = [[-200,-80,0],[0,0,-87],[30,0,0],[0,-25,0],[35,0,0],[0,30,0],[80,0,0],[0,-25,0],[20,-20,0],[40,0,0],[0,20,0],[-20,0,0],[-10,10,0],[0,15,0],[30,0,0],[0,20,0],[-30,0,0],[0,1000,0],[-30,0,0],[0,-100,0],[-80,0,0],[0,75,0],[50,50,0],[25,0,0],[0,20,0],[-45,0,0],[-20,-20,0],[0,-80,0],[-30,0,0],[0,-20,0],[0,0,80]]

def home():
  #+x 498 -x 100
  time.sleep(1)
  R.set_cartesian([[260, 200, 322.05-75], base_orientation]) 
  time.sleep(1)
  R.set_cartesian([[560, 200, 322.05-75], base_orientation])
  time.sleep(1)
  R.set_cartesian([[560, -200, 322.05-75], base_orientation])
  time.sleep(1)
  R.set_cartesian([[260, -200, 322.05-75], base_orientation])
  time.sleep(1)
  R.set_cartesian([[260, 200, 322.05-75], base_orientation]) 
  

def draw_logo(a,b,c,d,e,f,delay=1):
    R.clear_buffer()  
    coordinates = [[d/a,e/b,f/c],[0,0,-87],[50,0,0],[0,20,0],[-30,0,0],[0,30,0],[-20,0,0],[0,-50,0],[0,0,87],[65,0,0],[0,0,-87],[50,0,0],[0,50,0],[-20,0,0],[0,-30,0],[-30,0,0],[0,-20,0],[0,0,87],[-65,65,0],[0,0,-87],[20,0,0],[0,30,0],[30,0,0],[0,20,0],[-50,0,0],[0,-50,0],[0,0,87],[70,30,0],[0,0,-87],[30,0,0],[0,-25,0],[35,0,0],[0,30,0],[80,0,0],[0,-25,0],[20,-20,0],[40,0,0],[0,20,0],[-20,0,0],[-10,10,0],[0,15,0],[30,0,0],[0,20,0],[-30,0,0],[0,100,0],[-30,0,0],[0,-100,0],[-80,0,0],[0,75,0],[5,5,0],[25,0,0],[0,20,0],[-45,0,0],[-20,-20,0],[0,-80,0],[-30,0,0],[0,-20,0],[0,0,87],[225,35,0],[0,0,-87],[20,-20,0],[30,-15,0],[30,0,0],[30,15,0],[20,20,0],[0,50,0],[-20,20,0],[-30,15,0],[-30,0,0],[-30,-15,0],[-20,-20,0],[0,-50,0],[0,0,87],[32.5,12.5,0],[0,0,-87],[10,-10,0],[15,-7.5,0],[15,0,0],[15,7.5,0],[10,10,0],[0,25,0],[-10,10,0],[-15,7.5,0],[-15,0,0],[-15,-7.5,0],[-10,-10,0],[0,-25,0],[0,0,87],[-345,-160,0]]
    R.set_cartesian([[560, 200, 322.05-60], base_orientation])
    for i in coordinates:
        var_coordinates[0] += a*i[0]
        var_coordinates[1] += b*i[1]
        var_coordinates[2] += c*i[2]
        R.buffer_add([var_coordinates, base_orientation])
        time.sleep(delay)
    input("Start?")
    R.buffer_execute()
  
    

def draw_roulette():

  nTurns = 3

  rad = 40.0
  nPoints = 20

  R.set_joints([0.,45.,0.,0.,40.,0.]);
"""
  for ll in range(nTurns):
    for kk in range(nPoints):
      R.set_cartesian([[460.0+rad*math.sin(2*math.pi*kk/nPoints), 0.0+rad*math.cos(2*math.pi*kk/nPoints), 245.0], base_orientation])
"""

def spin():
  pass

#R.set_cartesian([[560, 200, 322.05], base_orientation])
draw_roulette();
#draw_logo(0.6,-0.6,0.45,-250,0,0,0.0)
#R.set_cartesian([base_coordinates, base_orientation])



"""
delta = 0
while True:
  delta -= 1
  R.set_cartesian([[base_coordinates[0],base_coordinates[1]+delta,base_coordinates[2]], base_orientation])
  print([base_coordinates[0],base_coordinates[1]+delta,base_coordinates[2], base_orientation])
  time.sleep(0.1)
"""

doRect = 0
doCirc = 0
doCircToolDown = 0
doWrite = 0


if doRect:
  nRect = 3

  R.set_joints([0.,45.,0.,0.,-40.,0.]);
  for kk in range(nRect):
    R.set_cartesian([[474.0, 0.0, 350.0], [0.7,0.0,0.7, 0.0]])

    R.set_cartesian([[474.0, 0.0, 150.0], [0.7,0.0,0.7, 0.0]])

    R.set_cartesian([[474.0, 200.0, 150.0], [0.7,0.0,0.7, 0.0]])

    R.set_cartesian([[474.0, 200.0, 350.0], [0.7,0.0,0.7, 0.0]])

  R.set_cartesian([[474.0, 0.0, 350.0], [0.7,0.0,0.7, 0.0]])


if doCirc:
  nTurns = 5

  rad = 80.0
  nPoints = 20

  for ll in range(nTurns):
    for kk in range(nPoints):
      R.set_cartesian([[474.0, 0.0+rad*math.cos(2*math.pi*kk/nPoints), 350.0+rad*math.sin(2*math.pi*kk/nPoints)], [0.7,0.0,0.7, 0.0]])


if doCircToolDown:
  nTurns = 5

  rad = 80.0
  nPoints = 20

  R.set_joints([0.,45.,0.,0.,40.,0.]);

  for ll in range(nTurns):
    for kk in range(nPoints):
      R.set_cartesian([[460.0+rad*math.sin(2*math.pi*kk/nPoints), 0.0+rad*math.cos(2*math.pi*kk/nPoints), 245.0], [0.0,0.0,1.0, 0.0]])

if doWrite:
  R.set_joints([0.,45.,0.,0.,-40.,0.]);









