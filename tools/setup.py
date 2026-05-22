from setuptools import setup, find_packages

setup(
    name="see-world-tools",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "openai>=1.0.0",
        "pillow>=10.0.0",
    ],
)
