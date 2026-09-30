#!/bin/bash
# One-time setup on PythonAnywhere (free plan). In a PythonAnywhere "Bash" console run:
#
#   git clone -b render-deploy https://github.com/saif-siddiqui06/job-hunter.git
#   bash job-hunter/deploy/pythonanywhere_setup.sh
#
# It creates a virtualenv, installs the app, asks for your Gemini key and an invite code,
# and prints the exact values to enter on the Web tab.
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
VENV="$HOME/.virtualenvs/apply-rocket"
DATA_DIR="$HOME/apply-rocket-data"
PYTHON="python3.11"
SITE="https://${USER_NAME}.pythonanywhere.com"

echo "==> Creating virtualenv at $VENV"
"$PYTHON" -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
echo "==> Installing packages (takes a few minutes)"
"$VENV/bin/pip" install --quiet --no-cache-dir -r "$APP_DIR/requirements-web.txt"

mkdir -p "$DATA_DIR"
if [ -f "$APP_DIR/.env" ]; then
    echo "==> Keeping existing $APP_DIR/.env"
else
    read -rp "Gemini API key: " GEMINI_KEY
    read -rp "Invite code you and your friend will use to create accounts: " INVITE
    umask 077
    cat > "$APP_DIR/.env" <<EOF
AI_PROVIDER=gemini
GEMINI_API_KEY=${GEMINI_KEY}
SIGNUP_CODE=${INVITE}
APP_DATA_DIR=${DATA_DIR}
PUBLIC_BASE_URL=${SITE}
EOF
    echo "==> Saved settings to $APP_DIR/.env (only readable by you)"
fi

cat <<EOF

=====================================================================
Setup done. Now open the "Web" tab on PythonAnywhere:

 1. "Add a new web app" -> Next -> "Manual configuration" -> Python 3.11 -> Next
 2. Virtualenv:      $VENV
 3. Source code:     $APP_DIR
 4. Click the WSGI configuration file link, delete everything in it,
    paste the contents of:  $APP_DIR/deploy/pythonanywhere_wsgi.py
    replace YOUR_USERNAME with:  $USER_NAME   and save.
 5. Security: turn "Force HTTPS" on.
 6. Click the green "Reload" button, then open: $SITE
=====================================================================
EOF
