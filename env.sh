# Point the AWS CLI and every AWS SDK in this shell at the running emulator.
#   source ./env.sh
# The emulator writes these files itself when it starts (Linux and macOS).
EMU_DIR="${EMULATOR_HOME:-$HOME/.aws/emulator}/${EMULATOR_DATA_PORT:-9297}"
if [ ! -f "$EMU_DIR/config" ]; then
  echo "No running emulator found at $EMU_DIR. Start the emulator first." >&2
  return 1 2>/dev/null || exit 1
fi
export AWS_CONFIG_FILE="$EMU_DIR/config"
# Set explicitly so a corporate AWS_CA_BUNDLE already in the shell does not override the emulator's.
export AWS_CA_BUNDLE="$EMU_DIR/ca.pem"
if [ -f "$EMU_DIR/emulator_credentials" ]; then
  export AWS_SHARED_CREDENTIALS_FILE="$EMU_DIR/emulator_credentials"
  # Real AWS keys in the shell would take precedence over the file and be refused.
  unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
else
  # --auth off: any key is accepted.
  export AWS_ACCESS_KEY_ID=emulator AWS_SECRET_ACCESS_KEY=emulator
fi
unset AWS_PROFILE AWS_SESSION_TOKEN
echo "AWS CLI and SDKs in this shell now use the emulator ($(grep endpoint_url "$AWS_CONFIG_FILE" | cut -d= -f2 | tr -d ' '))."
