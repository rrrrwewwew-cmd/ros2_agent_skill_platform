from setuptools import find_packages, setup


package_name = 'robot_skill_author'


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
                '../../schemas/skill_author_request.schema.json',
                '../../schemas/skill_author_plan.schema.json',
                '../../schemas/skill_author_result.schema.json',
                '../../schemas/skill_author_evaluation_summary.schema.json',
            ],
        ),
    ],
    install_requires=['setuptools', 'jsonschema', 'PyYAML'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description='RAG-assisted governed ROS 2 Skill authoring pipeline.',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'author_robot_skill = robot_skill_author.cli:main',
            'approve_skill_candidate = robot_skill_author.approve_cli:main',
            'evaluate_skill_author = robot_skill_author.evaluate_cli:main',
        ],
    },
)
