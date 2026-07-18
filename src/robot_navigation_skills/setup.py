from setuptools import find_packages, setup


package_name = 'robot_navigation_skills'


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
    description='Governed read-only Nav2 path preview Skills.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'preview_safe_route = '
            'robot_navigation_skills.preview_ros:main',
        ],
    },
)
