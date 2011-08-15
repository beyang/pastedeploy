from setuptools import setup, find_packages


setup(
    name='PasteDeploy',
    version='1.5.1.dev1',
    description='Load, configure, and compose WSGI applications and servers',
    long_description=open('README').read(),
    classifiers=[
      'Development Status :: 5 - Production/Stable',
      'Intended Audience :: Developers',
      'License :: OSI Approved :: MIT License',
      'Programming Language :: Python',
      'Programming Language :: Python :: 2.5',
      'Programming Language :: Python :: 2.6',
      'Programming Language :: Python :: 2.7',
      'Programming Language :: Python :: 3',
      'Programming Language :: Python :: 3.1',
      'Programming Language :: Python :: 3.2',
      'Topic :: Internet :: WWW/HTTP',
      'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
      'Topic :: Internet :: WWW/HTTP :: WSGI',
      'Topic :: Internet :: WWW/HTTP :: WSGI :: Middleware',
      'Topic :: Software Development :: Libraries :: Python Modules',
      'Framework :: Paste',
      ],
    keywords='web wsgi application server',
    author='Ian Bicking',
    author_email='ianb@colorstudy.com',
    maintainer='Alex Gronholm',
    maintainer_email='alex.gronholm@nextday.fi',
    url='http://pythonpaste.org/deploy/',
    license='MIT',
    namespace_packages=['paste'],
    packages=find_packages(exclude=['tests']),
    include_package_data=True,
    zip_safe=False,
    test_suite='nose.collector',
    tests_require=['nose>=0.11'],
    extras_require={
      'Config': [],
      'Paste': ['Paste'],
      },
    entry_points="""
    [paste.filter_app_factory]
    config = paste.deploy.config:make_config_filter [Config]
    prefix = paste.deploy.config:make_prefix_middleware

    [paste.paster_create_template]
    paste_deploy=paste.deploy.paster_templates:PasteDeploy
    """,
)
