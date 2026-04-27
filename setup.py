from setuptools import setup, find_packages

setup(
    name="spindoctor",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.0",
        "rich>=13.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "spindoctor=spindoctor.cli:cli",
        ],
    },
    python_requires=">=3.9",
)
