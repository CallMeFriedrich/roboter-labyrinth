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

R.set_speed([150,150,50,5]) # speed: [robot TCP linear speed (mm/s), TCP orientation speed (deg/s), external axis linear, external axis orientation]


R.set_joints([0.,0.,0.,0.,0.,0.]);

time.sleep(1.0)

print(R.get_cartesian())





