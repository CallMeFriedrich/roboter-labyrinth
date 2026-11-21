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

R.set_speed([50,50,5,5]) # speed: [robot TCP linear speed (mm/s), TCP orientation speed (deg/s), external axis linear, external axis orientation]
# R.set_cartesian([[X,Y,Z], [Quaternions]]) XYT in mm, quaternions: [0,0,1,0] is "tool down", [1,0,0,0] is "tool up"

#print(R.get_cartesian())

R.set_joints([0.,45.,0.,0.,-45.,0]);

R.set_tool() # reset tool

print("setting new tool")
R.set_tool([[20,150,0], [0.707,0,-0.707,0]])

print(R.get_cartesian())


'''
time.sleep(1.0)

print("moving tool down")
R.set_cartesian([[500, 0, 300], [0,0,1,0]]) # tool down

input("Press Enter to continue...")

print("moving tool up")
R.set_cartesian([[500, 0, 300], [1,0,0,0]]) # tool up

input("Press Enter to continue...")



print("moving tool down")
R.set_cartesian([[200, 0, 400], [0,0,1,0]]) # tool down

input("Press Enter to continue...")

print("moving tool up")
R.set_cartesian([[200, 0, 400], [1,0,0,0]]) # tool up
'''










