from setuptools import find_packages, setup

setup(
    name="LogBar",
    version="0.4.11",
    description="A unified Logger and ProgressBar util with zero dependencies.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="ModelCloud",
    author_email="qubitium@modelcloud.ai",
    url="https://github.com/ModelCloud/LogBar",
    license="Apache-2.0",
    packages=find_packages(exclude=["tests*", "test*"]),
    python_requires=">=3",
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    keywords="logger logging progressbar progress bar cli terminal lightweight zero dependency tqdm tabulate",
)
