from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

packages = find_packages(where=".")

if "tests" in packages:
    packages.remove("tests")

setup(
    name='TwitchEventSub',
    version='0.1.4',
    packages=packages,
    url='https://github.com/CPSuperstore/TwitchEventSub',
    license='MIT',
    author='CPSuperstore',
    author_email='cpsuperstoreinc@gmail.com',
    description='The Python package for receiving EventSub notifications from Twitch over WebSocket',
    long_description=long_description,
    long_description_content_type="text/markdown",
    project_urls={
        "Bug Tracker": "https://github.com/CPSuperstore/TwitchEventSub/issues",
    },
    keywords=['Twitch', 'EventSub', 'Bot', "WebSocket", "Channel Points", "livestream"],
    install_requires=[],
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers'
    ]
)
