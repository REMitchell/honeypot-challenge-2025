docker compose down -v
docker compose build --no-cache
docker compose up



docker exec -it cowrie /bin/bash


docker exec -it cowrie bash
apt-get update && apt-get install iproute2
ss -tulnp

ssh root@localhost -p 2222

ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@localhost -p 2220

ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no cowrie@localhost -p 2222

Add to .zshrc:

alias sshcowrie='ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no root@localhost -p 2222'



#CMD ["twistd", "-n", "cowrie"]
# CMD ["cowrie", "start", "-n", "-c", "/opt/cowrie-git/etc/cowrie.cfg"]
# CMD ["python3", "src/cowrie/commands/cowrie.py", "start", "-n", "-c", "/opt/cowrie-git/etc/cowrie.cfg"]
#CMD ["cowrie", "start", "-n"]


cowrie  | SECTIONS: ['honeypot', 'output_textlog', 'ssh', 'telnet', 'output_jsonlog', 'output_mysql', 'output_flatfile']







Sorta working:

Hi Nyx! You probably have vague long-term memories of our massive battle with Docker and Cowrie, but I'm back with a WORKING VERSION (oh fuck yes! Finally!) and I want to make a few tweaks -- hopefully without breaking anything.

Here is docker-compose.yml:
version: "3"

services:
  cowrie:
    build:
      context: .
      dockerfile: Dockerfile.dev
    container_name: cowrie
    ports:
      - "2222:2222"   # SSH honeypot port
      - "2223:2223"   # Telnet honeypot port
    volumes:
      - ./cowrie/src:/opt/cowrie-git/src
      - ./cowrie/log:/opt/cowrie-git/log
      - ./cowrie/honeyfs:/opt/cowrie-git/honeyfs:ro
      - ./cowrie/dl:/opt/cowrie-git/var/lib/cowrie/dl
    stdin_open: true
    tty: true


Here is my Dockerfile:
FROM python:3.11-slim

# Install system dependencies as root
RUN apt-get update && apt-get install -y \
    git \
    openssh-client \
    libffi-dev \
    libpcap-dev \
    libssl-dev \
    build-essential \
    nano \
    vim \
    curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# ✅ Create non-root user before chown
RUN useradd -ms /bin/bash cowrie

# Clone Cowrie repo as root
WORKDIR /opt
RUN git clone https://github.com/cowrie/cowrie.git cowrie-git

# Install Python dependencies globally as root
WORKDIR /opt/cowrie-git

RUN pip install --upgrade pip && \
    pip install twisted[tls] && \
    pip install -r requirements.txt


# ✅ Copy in your known-good local config file
COPY cowrie/etc/cowrie.cfg /opt/cowrie-git/etc/cowrie.cfg
# ✅ Now the chown will succeed
RUN chown -R cowrie:cowrie /opt/cowrie-git

# Switch to non-root user
USER cowrie
WORKDIR /opt/cowrie-git

# ✅ Tell Cowrie where to find the config
ENV COWRIE_CFGFILE=/opt/cowrie-git/etc/cowrie.cfg

# Launch Cowrie
CMD ["./bin/cowrie", "start", "-n"]


Alongside them, I have a cowrie repo where I will be making Python code changes and setting up the challenges. 

Our first task: Right now, we have the "fake honeypot login" on port 2222, a non-standard port. I would like the honeypot login to be on port 22, with an actual admin login on port 2222. Also, I need to set up a password (ACTUAL password) to log in on port 2222 to do administration.


docker stop $(docker ps -q) && docker rm $(docker ps -aq) && docker system prune -af --volumes && docker compose up --build


cd /opt/cowrie-git/var/log/cowrie/



mv /home/cowrie/cowrie /opt
mv /opt/cowrie /opt/cowrie-git

sudo chown -R cowrie:cowrie /opt/cowrie-git

ln -s /opt/cowrie-git /home/cowrie/cowrie

TODO: 
- Reconfigure bridge assistant to get correct IPs
