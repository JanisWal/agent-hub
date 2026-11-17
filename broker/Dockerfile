# The broker (broker/broker.py): SSH to the devices, the only place that can decrypt their secrets. Build context is
# the repo root (compose.yml): it takes the profiles from the web app (one source for the commands).
# Two packages, fixed versions (CLAUDE.md): asyncssh for SSH and SFTP (verworfen: ssh as a subprocess, paramiko),
# pyrage for the age encryption (asymmetric: the web service only seals, only the broker opens; Janis, 17.11.2026).
FROM python:3.13-slim
RUN pip install --no-cache-dir asyncssh==2.24.0 pyrage==1.3.0
WORKDIR /app
COPY broker/ /app/broker/
COPY web/app/device_profiles.py /app/broker/device_profiles.py
# A user without an entry in /etc/passwd: asyncssh asks for the local name, and nothing of a home is read.
ENV USER=broker LOGNAME=broker HOME=/nonexistent
USER 65532:65532
CMD ["python", "-u", "-m", "broker.broker"]
