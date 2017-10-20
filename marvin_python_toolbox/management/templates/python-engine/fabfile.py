#!/usr/bin/env python
# coding=utf-8

"""
Fabric file.

This file defines provisioning and deployment tasks for a Marvin engine.
"""

from fabric.api import env
from fabric.api import run
from fabric.api import execute
from fabric.api import cd
from fabric.api import local
from fabric.api import put
from fabric.api import sudo
from fabric.state import output
from marvin_python_toolbox import __version__ as TOOLBOX_VERSION
from marvin_python_toolbox.common.config import Config

_port = Config.get("port", section="ssh_deployment")
_user = Config.get("user", section="ssh_deployment")

env.hosts = ["{}@{}:{}".format(_user, h, _port) for h in Config.get("hosts", section="ssh_deployment").split(",")]

output["everything"] = False
output["running"] = True

env.package = "{{project.package}}"
env.margin_engine_executor_prefix = "/opt/marvin/engine-executor"
env.margin_engine_executor_jar = "marvin-engine-executor-assembly-{version}.jar".format(version=TOOLBOX_VERSION)
env.marvin_engine_executor_path = env.margin_engine_executor_prefix + "/" + env.margin_engine_executor_jar

def install_oracle_jdk():
    sudo("add-apt-repository ppa:webupd8team/java -y")
    sudo("apt-get -qq update")
    run("echo debconf shared/accepted-oracle-license-v1-1 select true | sudo debconf-set-selections")
    run("echo debconf shared/accepted-oracle-license-v1-1 seen true | sudo debconf-set-selections")
    sudo("apt-get install -y oracle-java8-installer")

def install_virtualenvwrapper():
    sudo("pip install virtualenvwrapper")
    run("echo 'export WORKON_HOME=${HOME}/.virtualenvs' >> ${HOME}/.profile")
    run("echo 'source /usr/local/bin/virtualenvwrapper.sh' >> ${HOME}/.profile")

def install_apache_spark():
    run("curl https://d3kbcqa49mib13.cloudfront.net/spark-2.1.1-bin-hadoop2.6.tgz -o /tmp/spark-2.1.1-bin-hadoop2.6.tgz")
    sudo("tar -xf /tmp/spark-2.1.1-bin-hadoop2.6.tgz -C /opt/")
    sudo("ln -s /opt/spark-2.1.1-bin-hadoop2.6 /opt/spark")
    run("echo 'export SPARK_HOME=/opt/spark' >> ${HOME}/.profile")

def install_required_packages():
    sudo("apt-get update -y")
    sudo("apt-get install -y git")
    sudo("apt-get install -y wget")
    sudo("apt-get install -y python2.7-dev")
    sudo("apt-get install -y python-pip")
    sudo("apt-get install -y ipython")
    sudo("apt-get install -y libffi-dev")
    sudo("apt-get install -y libssl-dev")
    sudo("apt-get install -y libxml2-dev")
    sudo("apt-get install -y libxslt1-dev")
    sudo("apt-get install -y libpng12-dev")
    sudo("apt-get install -y libfreetype6-dev")
    sudo("apt-get install -y python-tk")
    sudo("apt-get install -y libsasl2-dev")
    sudo("apt-get install -y python-pip")
    sudo("apt-get install -y graphviz")
    sudo("pip install --upgrade pip")

def install_marvin_engine_executor():
    sudo("mkdir -p {prefix}".format(prefix=env.margin_engine_executor_prefix))
    with cd("{prefix}".format(prefix=env.margin_engine_executor_prefix)):
        sudo("wget https://s3.amazonaws.com/marvin-engine-executor/{jar}".format(jar=env.margin_engine_executor_jar))

def create_marvin_engines_prefix():
    sudo("mkdir -p /opt/marvin/engines")
    sudo("chown {user}:{user} /opt/marvin/engines".format(user=env.user))
    sudo("mkdir -p /var/log/marvin/engines")
    sudo("chown {user}:{user} /var/log/marvin/engines".format(user=env.user))
    sudo("mkdir -p /var/run/marvin/engines")
    sudo("chown {user}:{user} /var/run/marvin/engines".format(user=env.user))

def configure_marvin_environment():
    run("echo 'export MARVIN_HOME=${HOME}/marvin' >> ${HOME}/.profile")
    run("echo 'export MARVIN_DATA_PATH=${MARVIN_HOME}/data' >> ${HOME}/.profile")
    run("mkdir -p ${MARVIN_HOME}")
    run("mkdir -p ${MARVIN_DATA_PATH}")

def provision():
    execute(install_required_packages)
    execute(install_virtualenvwrapper)
    execute(install_oracle_jdk)
    execute(install_apache_spark)
    execute(install_marvin_engine_executor)
    execute(create_marvin_engines_prefix)
    execute(configure_marvin_environment)

def package(version):
    package = env.package
    local("mkdir -p .packages")
    local("tar czvf {package}-{version}.tar.gz --exclude='.packages' --exclude='.vagrant' .".format(
        package=package, version=version))
    local("mv {package}-{version}.tar.gz .packages".format(
        package=package, version=version))

def deploy(version):
    package = env.package
    put(local_path=".packages/{package}-{version}.tar.gz".format(
        package=package, version=version), remote_path="/tmp/")
    run("mkdir -p /opt/marvin/engines/{package}/{version}".format(
        package=package, version=version))
    with cd("/opt/marvin/engines/{package}/{version}".format(
        package=package, version=version)):
        run("tar xzvf /tmp/{package}-{version}.tar.gz".format(
            package=package, version=version))
    with cd("/opt/marvin/engines/{package}".format(package=package)):
        symlink_exists = run("stat current", quiet=True).succeeded
        if (symlink_exists):
            run("rm current")
        run("ln -s {version} current".format(version=version))
    with cd("/opt/marvin/engines/{package}/current".format(package=package)):
        run("mkvirtualenv {package}_env".format(package=package))
        run("setvirtualenvproject")
        run("workon {package}_env && make marvin".format(
            package=package))

def engine_start(host, port):
    package = env.package

    command = (
        "workon {package}_env &&"
        " (marvin engine-httpserver"
        " -h {host}"
        " -p {port}"
        " -e {executor}"
        " 1> /var/log/marvin/engines/{package}.out"
        " 2> /var/log/marvin/engines/{package}.err"
        " & echo $! > /var/run/marvin/engines/{package}.pid)"
    ).format(
        package=package,
        host=host,
        port=port,
        executor=env.marvin_engine_executor_path
    )

    with cd("/opt/marvin/engines/{package}/current".format(package=package)):
        run(command, pty=False)

def engine_stop():
    package = env.package

    with cd("/opt/marvin/engines/{package}/current".format(package=package)):
        children_pids = run("ps --ppid $(cat /var/run/marvin/engines/{package}.pid) -o pid --no-headers |xargs echo".format(
            package=package))
        run("kill $(cat /var/run/marvin/engines/{package}.pid) {children_pids}".format(
            package=package, children_pids=children_pids))
    run("rm /var/run/marvin/engines/{package}.pid".format(package=package))

def engine_status():
    package = env.package
    pid_file_exists = run("cat /var/run/marvin/engines/{package}.pid".format(
        package=package), quiet=True)
    if pid_file_exists.succeeded:
        is_running = run("ps $(cat /var/run/marvin/engines/{package}.pid)".format(package=package), quiet=True)
        if is_running.succeeded:
            print "Your engine is running :)"
        else:
            print "Your engine is not running :("
    else:
        print "Your engine is not running :("
