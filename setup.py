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
    extras_require={
        # Lossless XML round-trip (preserves comments, attribute order).
        # Strongly recommended when sharing a HyperSpin install with HyperHQ.
        "xml": ["lxml>=4.9"],
        "dev": ["pytest>=7.0", "lxml>=4.9"],
    },
    entry_points={
        "console_scripts": [
            "spindoctor=spindoctor.cli:cli",
            # Standalone helpers — designed to run on boot or from the
            # HyperSpin Tools menu without loading the full CLI.
            "spindoctor-fav=spindoctor.favorites:main",
            "spindoctor-recent=spindoctor.recent:main",
        ],
    },
    python_requires=">=3.9",
)
