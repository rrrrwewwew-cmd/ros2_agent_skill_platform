from setuptools import find_packages, setup


package_name = 'robot_diagnosis_agent'


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
                '../../schemas/diagnosis_agent_result.schema.json',
                '../../schemas/mcp_tool_result.schema.json',
            ],
        ),
    ],
    install_requires=['setuptools', 'jsonschema'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description='Persistent evidence-first MiMo and MCP diagnosis Agent.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'run_diagnosis_agent = robot_diagnosis_agent.cli:main',
        ],
    },
)
