from pathlib import Path

from setuptools import find_packages, setup


package_name = 'robot_agent_orchestrator'
repository_root = Path(__file__).resolve().parents[2]


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml']),
        (
            'share/' + package_name + '/schemas',
            [
                '../../schemas/agent_loop_result.schema.json',
                '../../schemas/skill_execution_result.schema.json',
            ],
        ),
    ],
    install_requires=['setuptools', 'jsonschema'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description=(
        'Bounded read-only Agent Loop over MiMo and governed ROS 2 Skills.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'run_read_only_agent = robot_agent_orchestrator.cli:main',
        ],
    },
)
