from setuptools import find_packages, setup


package_name = 'robot_diagnosis_mcp'
schema_files = [
    '../../schemas/diagnosis_report_bundle.schema.json',
    '../../schemas/mcp_tool_result.schema.json',
]


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/schemas', schema_files),
    ],
    install_requires=[
        'setuptools',
        'jsonschema',
        'mcp>=1.27,<2',
    ],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description=(
        'Governed MCP tools for hash-verified robot experiment diagnosis.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'diagnosis_mcp_server = robot_diagnosis_mcp.server_cli:main',
            'diagnosis_mcp_smoke = robot_diagnosis_mcp.protocol_smoke:main',
        ],
    },
)
