"""Setup script for CAWL - Local Agent System."""

from setuptools import setup, find_packages

setup(
    name="cawl",
    version="0.3.0",
    description="CAWL - Local AI Agent powered by Ollama",
    packages=find_packages(exclude=["cawl_agent", "cawl_agent.*"]),
    install_requires=[
        "pyyaml",
        "requests",
        "colorama",
        "PyQt5>=5.15.0",
        "prompt_toolkit>=3.0.0",
    ],
    entry_points={
        "console_scripts": [
            "cawl=cawl.cli.main:main",
        ],
    },
    python_requires=">=3.10",
)
