from setuptools import setup, find_packages

setup(
    name='pybot-lcd-fuse',
    setup_requires=['setuptools_scm'],
    use_scm_version=True,
    namespace_packages=['pybot'],
    packages=find_packages("src"),
    package_dir={'': 'src'},
    url='',
    license='',
    author='Eric Pascual',
    author_email='eric@pobot.org',
    install_requires=['pybot-lcd', 'fusepy'],
    download_url='https://github.com/Pobot/PyBot',
    description='LCD access through fuse',
)
