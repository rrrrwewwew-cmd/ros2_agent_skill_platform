from setuptools import find_packages, setup


package_name = 'robot_semantic_skills'


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
    description=(
        'Deterministic read-only semantic map Skills for governed agents.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'query_semantic_target = '
            'robot_semantic_skills.query_cli:main',
        ],
    },
)
