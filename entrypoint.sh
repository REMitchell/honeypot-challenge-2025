#!/bin/bash
# Start real SSH server for admin access
/usr/sbin/sshd

# Start Cowrie as non-root user
sudo -u cowrie -E /opt/cowrie-git/bin/cowrie start -n