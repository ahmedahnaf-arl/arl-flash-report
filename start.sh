#!/bin/bash
apt-get update && apt-get install -y curl gnupg2 unixodbc-dev

curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft.gpg
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft.gpg] https://packages.microsoft.com/ubuntu/22.04/prod jammy main" > /etc/apt/sources.list.d/mssql-release.list
apt-get update
ACCEPT_EULA=Y apt-get install -y msodbcsql18

echo "Starting ARL Flash Report..."
exec python live_server.py --port ${PORT:-8080} --host 0.0.0.0 --no-browser
