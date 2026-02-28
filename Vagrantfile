Vagrant.configure("2") do |config|
  config.vm.box = "almalinux/10"
  config.vm.network "forwarded_port", guest: 9990, host: 9990
  config.vm.provision "shell", path: "vagrant/provision.sh"
end
