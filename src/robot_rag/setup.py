from pathlib import Path

from setuptools import find_packages, setup


package_name = 'robot_rag'
repository_root = Path(__file__).resolve().parents[2]
schema_files = sorted(
    '../../schemas/' + path.name
    for path in (repository_root / 'schemas').glob('rag_*.schema.json')
)
corpus_root = repository_root / 'rag/corpora/robotics_core_v1'
corpus_data_files = []
for path in sorted(corpus_root.rglob('*')):
    if not path.is_file():
        continue
    relative = path.relative_to(corpus_root)
    install_dir = (
        'share/' + package_name + '/corpora/robotics_core_v1/' +
        str(relative.parent)
    )
    source_path = '../../rag/corpora/robotics_core_v1/' + str(relative)
    corpus_data_files.append((install_dir, [source_path]))


setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
         ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/schemas', schema_files),
        *corpus_data_files,
    ],
    install_requires=['setuptools', 'jsonschema'],
    zip_safe=True,
    maintainer='rrrrwewwew-cmd',
    maintainer_email='maintainer@example.com',
    description=(
        'Versioned hybrid RAG with learned multilingual embeddings, '
        'abstention and reproducible A/B evaluation.'
    ),
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'rag_build = robot_rag.build_cli:main',
            'rag_query = robot_rag.query_cli:main',
            'rag_evaluate = robot_rag.evaluate_cli:main',
            'rag_ab_evaluate = robot_rag.ab_evaluate_cli:main',
        ],
    },
)
