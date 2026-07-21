from setuptools import find_packages, setup


package_name = 'robot_controlled_navigation_skills'


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description='Human-approved and fail-closed Nav2 motion Skills.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'navigate_to_approved_pose = '
            'robot_controlled_navigation_skills.navigation_ros:main',
            'cancel_approved_navigation = '
            'robot_controlled_navigation_skills.cancel_ros:main',
        ],
    },
)
