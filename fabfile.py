from robfabric import *
from fabric.api import env
from fabric.state import output

env.hosts = ['rpi3']
output.output = False
