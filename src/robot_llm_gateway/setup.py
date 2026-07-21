from pathlib import Path

from setuptools import find_packages, setup


package_name = 'robot_llm_gateway'
repository_root = Path(__file__).resolve().parents[2]
schema_files = sorted(
    '../../schemas/' + path.name
    for path in (repository_root / 'schemas').glob('*.schema.json')
)
prompt_files = sorted(
    '../../prompts/robot_task_planner/' + path.name
    for path in (repository_root / 'prompts/robot_task_planner').glob('*.json')
)
prompt_eval_files = sorted(
    '../../prompts/robot_task_planner/evals/' + path.name
    for path in (
        repository_root / 'prompts/robot_task_planner/evals'
    ).glob('*.json')
)
diagnosis_prompt_files = sorted(
    '../../prompts/experiment_diagnosis_planner/' + path.name
    for path in (
        repository_root / 'prompts/experiment_diagnosis_planner'
    ).glob('*.json')
)
skill_author_prompt_files = sorted(
    '../../prompts/skill_author_planner/' + path.name
    for path in (
        repository_root / 'prompts/skill_author_planner'
    ).glob('*.json')
)


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/schemas', schema_files),
        ('share/' + package_name + '/prompts/robot_task_planner',
         prompt_files),
        ('share/' + package_name + '/prompts/robot_task_planner/evals',
         prompt_eval_files),
        (
            'share/' + package_name + '/prompts/'
            'experiment_diagnosis_planner',
            diagnosis_prompt_files,
        ),
        (
            'share/' + package_name + '/prompts/skill_author_planner',
            skill_author_prompt_files,
        ),
    ],
    install_requires=['setuptools', 'jsonschema'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description=(
        'Plan-only Xiaomi MiMo gateway and immutable Prompt Registry for '
        'the governed robot Agent.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'plan_robot_task = robot_llm_gateway.cli:main',
            'evaluate_robot_planner = robot_llm_gateway.evaluate_cli:main',
        ],
    },
)
