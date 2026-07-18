#!/usr/bin/env bash
# Install git hooks for this repo. Idempotent.
# Hooks:
#   commit-msg: validate Conventional Commits format via scripts/validate-commit-msg.py
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

mkdir -p "$HOOKS_DIR"

# commit-msg: validate format
cat > "$HOOKS_DIR/commit-msg" <<EOF
#!/usr/bin/env bash
# Installed by scripts/install-hooks.sh
exec "$PROJECT_ROOT/scripts/validate-commit-msg.py" "\$1"
EOF
chmod +x "$HOOKS_DIR/commit-msg"

echo "Installed hooks:"
echo "  $HOOKS_DIR/commit-msg"
echo "To enable globally: just re-run this script after each clone."