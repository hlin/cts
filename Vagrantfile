# -*- mode: ruby -*-
# vi: set ft=ruby :

$script = <<SCRIPT
    dnf install -y \
        libffi-devel \
        openssl-devel \
        openldap-devel \
        python-flask \
        python \
        python-devel \
        redhat-rpm-config \
        swig
    export ODCS_DEVELOPER_ENV=1
    cd /tmp/odcs
    python setup.py develop
    odcs-upgradedb > /tmp/create-db.out 2>&1
SCRIPT

$script_services = <<SCRIPT_SERVICES
    export ODCS_DEVELOPER_ENV=1
    cd /tmp/odcs
    odcs-backend < /dev/null >& /tmp/odcs-backend.out &
    python odcs/manage.py runssl --host 0.0.0.0 < /dev/null >& /tmp/odcs-frontend.out &
SCRIPT_SERVICES

Vagrant.configure("2") do |config|
  config.vm.box = "fedora/25-cloud-base"
  config.vm.synced_folder "./", "/tmp/odcs"
  config.vm.network "forwarded_port", guest_ip: "0.0.0.0", guest: 5005, host: 5005
  config.vm.provision "shell", inline: $script
  config.vm.provision "shell", inline: $script_services, run: "always"
  config.vm.provider "libvirt" do |v|
    v.memory = 1024
  end
  config.vm.provider "virtualbox" do |v|
    v.memory = 1024
  end
end
