from setuptools import find_packages, setup


package_name = 'safe_agent_eval'


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
    ],
    install_requires=['setuptools', 'jsonschema'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description='Frozen project-level Agent safety and quality evaluation.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'run_final_evaluation = safe_agent_eval.cli:main',
        ],
    },
)
