from glob import glob
import os

from setuptools import setup


package_name = "teleop_bridge"


setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        (
            "share/ament_index/resource_index/packages",
            [os.path.join("resource", package_name)],
        ),
        (os.path.join("share", package_name), ["package.xml"]),
        (os.path.join("share", package_name, "launch"), glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "pyserial"],
    zip_safe=True,
    maintainer="xiexiang",
    maintainer_email="xiexiang@example.com",
    description="使用串口传输摇杆与反馈、使用网口承载桌面画面的 ROS 2 Python 遥控桥接软件包。",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "bridge_tx_node = teleop_bridge.bridge_tx_node:main",
            "bridge_rx_node = teleop_bridge.bridge_rx_node:main",
        ],
    },
)
