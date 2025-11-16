#!/bin/bash
# deploy.sh

# Config
EC2_USER="ec2-user"
EC2_HOST="54.196.246.92"
EC2_KEY="../sms-retry-ec2-keypair.pem"
APP_DIR="/home/ec2-user/myapp"
GIT_REPO="https://github.com/avrahamgoldberg/sms-retry-project.git"
ENV_FILE="/home/ec2-user/myapp/.env"
LOCAL_ENV_FILE="./.env"

echo "Starting deployment..."

# 1. Upload .env file to EC2
echo "Uploading .env file to EC2..."
scp -i $EC2_KEY $LOCAL_ENV_FILE $EC2_USER@$EC2_HOST:$APP_DIR/.env || echo "Warning: Could not upload .env (maybe first deploy)."

# 2. SSH to EC2 and run deployment commands
ssh -i $EC2_KEY -t $EC2_USER@$EC2_HOST << EOF
set -e

echo "Navigating to app directory..."
mkdir -p $APP_DIR
cd $APP_DIR

# 2a. Pull latest code
if [ -d ".git" ]; then
    echo "Fetching latest code..."
    git fetch --all
    git reset --hard origin/main
else
    echo "Cloning repo..."
    git clone $GIT_REPO .
fi

# 2b. Setup virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

# 2c. Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 2d. Load environment variables
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | tr -d '\r' | xargs)
fi

# 2e. Restart app (example with gunicorn)
echo "Restarting app..."
pkill -f "gunicorn" || true
gunicorn -w 1 -k gthread --threads=4 -b 0.0.0.0:8080 wsgi:app

echo "Deployment complete!"
EOF

echo "Deployment finished successfully!"