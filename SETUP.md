# Setup guide for **Stretch RE1**

## Install Ubuntu

1. Download the [Ubuntu 20.04 desktop image](https://old-releases.ubuntu.com/releases/20.04/) and flash it to a USB drive using [Etcher](https://www.balena.io/etcher/).
2. Connect the USB drive, monitor, keyboard, and mouse to the robot.
3. Power on the robot. At the BIOS screen, press **F10** to open the boot menu and select the USB drive.
4. Complete the installation by following the official [Install Ubuntu 20.04 guide](https://docs.hello-robot.com/0.3/installation/install_ubuntu_20.04/).

## Run the robot installation script

1. Open a terminal and install dependencies:
  ```bash
   sudo apt update
   sudo apt install git zip
  ```
2. Restore the robot's calibration data in your home folder (`~/`). You need a directory named `stretch-re1-<XXXX>`, where `<XXXX>` is your robot's serial number.
3. Clone the [stretch_install](https://github.com/hello-robot/stretch_install) repository and run the script:
  ```bash
   cd ~/
   git clone https://github.com/hello-robot/stretch_install
   cd stretch_install
   git pull
   ./stretch_new_robot_install.sh
  ```
   The script takes 20–30 minutes to complete. See [installation log](documentation-files/installation-log.txt) for a full log of a successful installation.


Reference: [Run the new robot installation script](https://docs.hello-robot.com/0.2/stretch-install/docs/robot_install/)

## Post-install steps

1. Reboot the robot before continuing so all install changes take effect, then apply the [stretch_body](https://github.com/hello-robot/stretch_body) bugfix for Python 3.8:
  ```bash
   cd ~/
   git clone https://github.com/hello-robot/stretch_body.git
   cd stretch_body
   git checkout bugfix/remove-list-annotation-for-py38
   git pull
   cd body
   python3 -m pip install -e .
  ```
2. Run migration and firmware tools:
  ```bash
   RE1_migrate_params.py
   RE1_migrate_contacts.py
   REx_firmware_updater.py --install
  ```

Reference: [Post install steps](https://docs.hello-robot.com/0.3/installation/robot_install/#post-install-steps)

## Troubleshooting

- If URDF or visualization tools fail with a `pycollada` error:

```bash
pip install pycollada==0.8
```

- To verify hardware communication:

```bash
REx_dynamixel_id_scan.py /dev/hello-dynamixel-wrist
REx_discover_hello_devices.py --list
```

## Home procedure and system check

Home the robot, then run the system check:

```bash
stretch_robot_home.py
stretch_system_check.py
```

`stretch_robot_home.py` must complete successfully before running motion tests in `[tests/](tests/)`.

Expected result: hardware, firmware, and Python packages report **Pass**. See [calibration log](documentation-files/calibration-log.txt) and [complete homing procedure video](documentation-files/complete-homing-procedure-video.MOV) from a successful homing and system check.

## VNC viewer setup

Use these steps on the robot to enable screen sharing over VNC.

1. Install Vino

```bash
sudo apt update
sudo apt install vino
```

2. Enable screen sharing

Open **Settings → Sharing**:

a. Turn **Sharing** on.
b. Open **Screen Sharing**.
c. Enable **Screen sharing**.
d. Enable **Remote control**.
e. Set a VNC password.
f. Disable encryption requirement**

Some VNC clients cannot connect when encryption is required. Run:

```bash
gsettings set org.gnome.Vino require-encryption false
```

3. Get the robot IP address

On the robot, run:

```bash
hostname -I
```

Use the first IP address shown to connect from your VNC viewer.