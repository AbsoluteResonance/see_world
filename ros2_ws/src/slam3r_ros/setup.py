from setuptools import find_packages, setup

package_name = 'slam3r_ros'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='See World',
    maintainer_email='see@world.dev',
    description='ROS2 wrapper for SLAM3R dense reconstruction',
    license='GPL-3.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'slam3r_node = slam3r_ros.node:main',
        ],
    },
)
